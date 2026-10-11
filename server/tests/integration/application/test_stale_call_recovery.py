from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.application.call.recovery import (
    INTERRUPTED_CALL_SUMMARY,
    StaleCallRecoveryService,
    recovery_settlement_digest,
)
from src.domain.call import CallContent, CallEndReason, CallOutcome, CallState, derive_call_conversation_id
from src.domain.conversation_type import ConversationItem
from src.infrastructure.persistence.call_sessions import CallSessionRecord, SettlementStatus, SqlCallSessionRepository
from src.infrastructure.persistence.database.redis_buffer import RedisBuffer
from src.infrastructure.persistence.database.services.conversation_service import ConversationService
from src.infrastructure.persistence.database.services.user_store import UserStore
from src.infrastructure.persistence.database.sql_database import Base, Conversation, User


class _Batches:
    def list_for_call(self, **kwargs):
        return ()


class _Verifier:
    def verify_completed_batch(self, batch):
        raise AssertionError("no completed batch expected")


def _fixture(path):
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False, "timeout": 30})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    redis = RedisBuffer()
    users = UserStore({}, sessions, redis)
    conversations = ConversationService(sql_session_factory=sessions, redis_buffer=redis, user_store=users)
    with sessions() as session:
        session.add(User(uuid="owner", username="owner", password="hash"))
        session.commit()
    return engine, sessions, SqlCallSessionRepository(sessions), conversations


def _record(state, now, **changes):
    record = CallSessionRecord(
        call_id=uuid4(),
        client_request_id=str(uuid4()),
        user_id="owner",
        character_id="luotianyi",
        state=state,
        requested_at=now - timedelta(minutes=3),
        created_at=now - timedelta(minutes=3),
        updated_at=now - timedelta(minutes=2),
    )
    return record.with_update(**changes)


def test_recovery_converges_concurrently_and_survives_sqlite_reopen(tmp_path):
    now = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)
    engine, sessions, repository, conversations = _fixture(tmp_path / "recovery.sqlite")
    preparing = _record(CallState.PREPARING, now)
    active = _record(
        CallState.ACTIVE,
        now,
        connected_at=now - timedelta(seconds=40),
        disconnected_at=now - timedelta(seconds=25),
        active_duration_ms=12_000,
    )
    repository.create_if_absent(preparing)
    repository.create_if_absent(active)

    def run_scan():
        return asyncio.run(
            StaleCallRecoveryService(
                call_sessions=repository,
                conversation_service=conversations,
                call_maintenance_batches=_Batches(),
                projection_verifier=_Verifier(),
                stale_after=timedelta(seconds=1),
                wall_clock=lambda: now,
            ).reconcile()
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        reports = list(pool.map(lambda _: run_scan(), range(2)))

    assert sum(report.failed for report in reports) == 0
    assert repository.find_by_id(preparing.call_id).state is CallState.FAILED
    terminal = repository.find_by_id(active.call_id)
    assert terminal.state is CallState.ENDED
    assert terminal.active_duration_ms == 15_000
    assert terminal.summary_status is SettlementStatus.SUCCEEDED
    assert terminal.maintenance_status is SettlementStatus.FAILED
    with sessions() as session:
        rows = session.query(Conversation).all()
        assert len(rows) == 1
        assert INTERRUPTED_CALL_SUMMARY in rows[0].content

    engine.dispose()
    reopened = create_engine(f"sqlite:///{tmp_path / 'recovery.sqlite'}")
    reopened_sessions = sessionmaker(bind=reopened)
    reopened_repository = SqlCallSessionRepository(reopened_sessions)
    reopened_conversations = ConversationService(
        sql_session_factory=reopened_sessions,
        redis_buffer=RedisBuffer(),
        user_store=UserStore({}, reopened_sessions, RedisBuffer()),
    )
    report = asyncio.run(
        StaleCallRecoveryService(
            call_sessions=reopened_repository,
            conversation_service=reopened_conversations,
            call_maintenance_batches=_Batches(),
            projection_verifier=_Verifier(),
            stale_after=timedelta(seconds=1),
            wall_clock=lambda: now + timedelta(minutes=1),
        ).reconcile()
    )
    assert report.scanned == 0
    assert reopened_repository.find_by_id(active.call_id).conversation_id == derive_call_conversation_id(
        user_id="owner", character_id="luotianyi", call_id=active.call_id
    )
    reopened.dispose()


def test_recovery_repairs_existing_terminal_projection_without_model_input(tmp_path):
    now = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)
    engine, sessions, repository, conversations = _fixture(tmp_path / "repair.sqlite")
    ended = _record(
        CallState.ENDED,
        now,
        outcome=CallOutcome.CONNECTED,
        end_reason=CallEndReason.SYSTEM_FAILURE,
        ended_at=now - timedelta(minutes=1),
        active_duration_ms=7_000,
        summary_status=SettlementStatus.FAILED,
        maintenance_status=SettlementStatus.PENDING,
    )
    repository.create_if_absent(ended)
    report = asyncio.run(
        StaleCallRecoveryService(
            call_sessions=repository,
            conversation_service=conversations,
            call_maintenance_batches=_Batches(),
            projection_verifier=_Verifier(),
            wall_clock=lambda: now,
        ).reconcile()
    )
    assert report == report.__class__(scanned=1, recovered=1, skipped=0, conflicted=0, failed=0)
    repaired = repository.find_by_id(ended.call_id)
    assert repaired.summary_status is SettlementStatus.SUCCEEDED
    assert repaired.maintenance_status is SettlementStatus.FAILED
    engine.dispose()


def test_recovery_digest_is_stable_and_conflict_preserves_existing_winner(tmp_path):
    now = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)
    engine, sessions, repository, conversations = _fixture(tmp_path / "digest-conflict.sqlite")
    ended = _record(
        CallState.ENDED,
        now,
        outcome=CallOutcome.CONNECTED,
        end_reason=CallEndReason.SYSTEM_FAILURE,
        ended_at=now,
        active_duration_ms=3_000,
        settlement_input_digest="b" * 64,
    )
    repository.create_if_absent(ended)
    first = recovery_settlement_digest(ended)
    second = recovery_settlement_digest(
        ended.with_update(updated_at=now + timedelta(hours=1), ended_at=now + timedelta(hours=1))
    )
    assert first == second
    report = asyncio.run(
        StaleCallRecoveryService(
            call_sessions=repository,
            conversation_service=conversations,
            call_maintenance_batches=_Batches(),
            projection_verifier=_Verifier(),
            wall_clock=lambda: now + timedelta(days=1),
        ).reconcile()
    )
    assert report == report.__class__(scanned=1, recovered=0, skipped=1, conflicted=0, failed=0)
    with sessions() as session:
        assert session.query(Conversation).count() == 0
    current = repository.find_by_id(ended.call_id)
    assert current.summary_status is SettlementStatus.PENDING
    assert current.maintenance_status is SettlementStatus.PENDING
    engine.dispose()


def test_existing_normal_digest_repairs_legal_winner_without_creating_fallback(tmp_path):
    now = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)
    engine, _, repository, conversations = _fixture(tmp_path / "normal-winner.sqlite")
    ended = _record(
        CallState.ENDED,
        now,
        outcome=CallOutcome.CONNECTED,
        end_reason=CallEndReason.SYSTEM_FAILURE,
        ended_at=now,
        active_duration_ms=3_000,
        settlement_input_digest="c" * 64,
    )
    repository.create_if_absent(ended)
    conversation_id = derive_call_conversation_id(
        user_id=ended.user_id, character_id=ended.character_id, call_id=ended.call_id
    )
    summary = "正常结算已经形成的概要"
    content = CallContent(
        call_id=ended.call_id,
        outcome=ended.outcome,
        active_duration_ms=ended.active_duration_ms,
        summary=summary,
        end_reason=ended.end_reason,
    )
    conversations.add_call_conversation(
        ended.user_id,
        ended.character_id,
        ConversationItem(
            uuid=str(conversation_id),
            timestamp=ended.requested_at.replace(tzinfo=None).isoformat(sep=" ", timespec="microseconds"),
            source="user",
            type="call",
            content=content.render_for_agent(),
            data={
                "call_id": str(ended.call_id),
                "outcome": ended.outcome.value,
                "active_duration_ms": ended.active_duration_ms,
                "summary": summary,
                "end_reason": ended.end_reason.value,
            },
        ),
    )
    report = asyncio.run(
        StaleCallRecoveryService(
            call_sessions=repository,
            conversation_service=conversations,
            call_maintenance_batches=_Batches(),
            projection_verifier=_Verifier(),
            wall_clock=lambda: now + timedelta(days=1),
        ).reconcile()
    )
    assert report.recovered == 1
    current = repository.find_by_id(ended.call_id)
    assert current.summary_status is SettlementStatus.SUCCEEDED
    assert current.maintenance_status is SettlementStatus.PENDING
    winner = conversations.get_call_conversation(
        str(conversation_id), user_id=ended.user_id, character_id=ended.character_id
    )
    assert winner.data["summary"] == summary
    engine.dispose()
