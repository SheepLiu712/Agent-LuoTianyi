"""Read-only, timestamp-bounded conversation seeds for call contexts."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from src.domain import ConversationItem
from src.infrastructure.persistence.database.redis_buffer import RedisBuffer
from src.infrastructure.persistence.database.services.conversation_service import ConversationService
from src.infrastructure.persistence.database.services.user_store import UserStore
from src.infrastructure.persistence.database.sql_database import (
    Base,
    CognitiveMaintenanceBatch,
    Conversation,
    ConversationContext,
    User,
)

REQUESTED_AT = datetime(2026, 10, 10, 12, 0, 0)


@pytest.fixture
def database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'call-seed.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as session:
        session.add(User(uuid="user", username="user", password="unused"))
        session.commit()
    redis = RedisBuffer()
    service = ConversationService(
        sql_session_factory=sessions,
        redis_buffer=redis,
        user_store=UserStore({}, sessions, redis),
    )
    return service, engine, sessions, redis


def _insert(session_factory, *, user_id, character_id, entry_id, timestamp, content=None):
    with session_factory() as session:
        session.add(
            Conversation(
                uuid=entry_id,
                user_id=user_id,
                character_id=character_id,
                timestamp=timestamp,
                source="user",
                type="text",
                content=content or entry_id,
            )
        )
        session.commit()


def _snapshot_counts(session_factory, redis):
    with session_factory() as session:
        conversation_count = session.query(Conversation).count()
        context_count = session.query(ConversationContext).count()
        batch_count = session.query(CognitiveMaintenanceBatch).count()
    return conversation_count, context_count, batch_count, dict(redis._store)


def _add_history_with_compacted_summary(service, total_count, retained_count):
    items = []
    for index in range(total_count):
        if index < 5:
            timestamp = REQUESTED_AT - timedelta(minutes=10, seconds=5 - index)
        elif index < 15:
            timestamp = REQUESTED_AT - timedelta(minutes=5, seconds=15 - index)
        else:
            timestamp = REQUESTED_AT - timedelta(seconds=total_count - index)
        items.append(
            ConversationItem(
                uuid=f"summary-{index:02d}",
                timestamp=timestamp.isoformat(sep=" ", timespec="microseconds"),
                source="user",
                content=f"内容 {index}",
                type="text",
            )
        )
    assert service.add_conversations("user", items, character_id="luotianyi") == [item.uuid for item in items]
    assert service.compact_conversation_context(
        "user",
        "可信总结",
        keep_recent_count=retained_count,
        expected_context_count=total_count,
        character_id="luotianyi",
    )


@pytest.mark.parametrize(
    ("total_count", "retained_count", "expected_first"),
    [(35, 30, 5), (40, 35, 10)],
)
def test_call_seed_keeps_provable_compacted_summary_and_latest_window(
    database, total_count, retained_count, expected_first
):
    service, engine, sessions, redis = database
    try:
        _add_history_with_compacted_summary(service, total_count, retained_count)

        state = service.get_call_conversation_seed_state("user", character_id="luotianyi", requested_at=REQUESTED_AT)

        assert state["summary"] == "可信总结"
        assert state["context_count"] == 30
        assert [entry["uuid"] for entry in state["conversations"]] == [
            f"summary-{index:02d}" for index in range(expected_first, total_count)
        ]
        assert [entry["content"] for entry in state["conversations"]] == [
            f"内容 {index}" for index in range(expected_first, total_count)
        ]
        assert "summary-00" not in {entry["uuid"] for entry in state["conversations"]}
        assert state["conversations"][0]["timestamp"] < (REQUESTED_AT - timedelta(minutes=3)).isoformat(
            sep=" ", timespec="microseconds"
        )
    finally:
        engine.dispose()


def test_call_seed_uses_exact_time_gate_and_retains_old_history_to_cap(database):
    service, engine, sessions, redis = database
    try:
        for index in range(35):
            _insert(
                sessions,
                user_id="user",
                character_id="luotianyi",
                entry_id=f"old-{index:02d}",
                timestamp=REQUESTED_AT - timedelta(days=1, seconds=35 - index),
            )
        _insert(
            sessions,
            user_id="user",
            character_id="luotianyi",
            entry_id="at-lower-bound",
            timestamp=REQUESTED_AT - timedelta(minutes=3),
        )
        _insert(
            sessions,
            user_id="user",
            character_id="luotianyi",
            entry_id="before-lower-bound",
            timestamp=REQUESTED_AT - timedelta(minutes=3, microseconds=1),
        )

        state = service.get_call_conversation_seed_state("user", character_id="luotianyi", requested_at=REQUESTED_AT)

        assert state["summary"] == ""
        assert state["context_count"] == 30
        assert [entry["uuid"] for entry in state["conversations"]] == [
            *(f"old-{index:02d}" for index in range(7, 35)),
            "before-lower-bound",
            "at-lower-bound",
        ]
    finally:
        engine.dispose()


def test_call_seed_excludes_future_rows_and_orders_identical_timestamps(database):
    service, engine, sessions, redis = database
    try:
        _insert(
            sessions,
            user_id="user",
            character_id="luotianyi",
            entry_id="same-z",
            timestamp=REQUESTED_AT,
        )
        _insert(
            sessions,
            user_id="user",
            character_id="luotianyi",
            entry_id="same-a",
            timestamp=REQUESTED_AT,
        )
        _insert(
            sessions,
            user_id="user",
            character_id="luotianyi",
            entry_id="future",
            timestamp=REQUESTED_AT + timedelta(microseconds=1),
        )

        state = service.get_call_conversation_seed_state("user", character_id="luotianyi", requested_at=REQUESTED_AT)

        assert [entry["uuid"] for entry in state["conversations"]] == ["same-a", "same-z"]
        assert state["context_count"] == 2
    finally:
        engine.dispose()


def test_call_seed_is_owner_scoped_read_only_and_uses_one_sql_snapshot(database):
    service, engine, sessions, redis = database
    try:
        _insert(
            sessions,
            user_id="user",
            character_id="luotianyi",
            entry_id="owner",
            timestamp=REQUESTED_AT,
        )
        _insert(
            sessions,
            user_id="user",
            character_id="other",
            entry_id="other-character",
            timestamp=REQUESTED_AT,
        )
        with sessions() as session:
            session.add(User(uuid="other-user", username="other-user", password="unused"))
            session.commit()
        _insert(
            sessions,
            user_id="other-user",
            character_id="luotianyi",
            entry_id="other-user",
            timestamp=REQUESTED_AT,
        )
        before = _snapshot_counts(sessions, redis)
        statements = []

        def capture(*args):
            statements.append(args[2])

        event.listen(engine, "before_cursor_execute", capture)
        try:
            state = service.get_call_conversation_seed_state(
                "user", character_id="luotianyi", requested_at=REQUESTED_AT
            )
        finally:
            event.remove(engine, "before_cursor_execute", capture)

        assert [entry["uuid"] for entry in state["conversations"]] == ["owner"]
        assert len(statements) == 1
        assert "WITH scoped_conversations" in statements[0]
        assert _snapshot_counts(sessions, redis) == before
    finally:
        engine.dispose()


def test_call_seed_missing_context_never_creates_one(database):
    service, engine, sessions, redis = database
    try:
        _insert(
            sessions,
            user_id="user",
            character_id="luotianyi",
            entry_id="recent",
            timestamp=REQUESTED_AT,
        )
        before = _snapshot_counts(sessions, redis)

        state = service.get_call_conversation_seed_state("user", character_id="luotianyi", requested_at=REQUESTED_AT)

        assert state["conversations"][0]["uuid"] == "recent"
        assert _snapshot_counts(sessions, redis) == before
    finally:
        engine.dispose()


def test_call_seed_returns_empty_when_latest_eligible_row_is_before_the_window(database):
    service, engine, sessions, redis = database
    try:
        _insert(
            sessions,
            user_id="user",
            character_id="luotianyi",
            entry_id="one-microsecond-too-old",
            timestamp=REQUESTED_AT - timedelta(minutes=3, microseconds=1),
        )

        state = service.get_call_conversation_seed_state("user", character_id="luotianyi", requested_at=REQUESTED_AT)

        assert state == {"summary": "", "conversations": [], "context_count": 0, "version": "0:0:"}
    finally:
        engine.dispose()


def test_call_seed_rejects_aware_requested_at(database):
    service, engine, sessions, redis = database
    try:
        with pytest.raises(ValueError, match="naive server-local"):
            service.get_call_conversation_seed_state(
                "user", character_id="luotianyi", requested_at=REQUESTED_AT.replace(tzinfo=timezone.utc)
            )
    finally:
        engine.dispose()


def test_call_seed_returns_empty_when_summary_cannot_be_proven_current(database):
    service, engine, sessions, redis = database
    try:
        _insert(
            sessions,
            user_id="user",
            character_id="luotianyi",
            entry_id="eligible",
            timestamp=REQUESTED_AT,
        )
        _insert(
            sessions,
            user_id="user",
            character_id="luotianyi",
            entry_id="compacted-after-request",
            timestamp=REQUESTED_AT + timedelta(microseconds=1),
        )
        with sessions() as session:
            session.add(
                ConversationContext(
                    user_id="user",
                    character_id="luotianyi",
                    context_summary="unverifiable summary",
                    context_memory_count=1,
                )
            )
            session.commit()

        state = service.get_call_conversation_seed_state("user", character_id="luotianyi", requested_at=REQUESTED_AT)

        assert state == {"summary": "", "conversations": [], "context_count": 0, "version": "0:0:"}
    finally:
        engine.dispose()


def test_call_seed_returns_empty_when_summary_count_is_not_a_valid_suffix(database):
    service, engine, sessions, redis = database
    try:
        _insert(
            sessions,
            user_id="user",
            character_id="luotianyi",
            entry_id="eligible",
            timestamp=REQUESTED_AT,
        )
        with sessions() as session:
            session.add(
                ConversationContext(
                    user_id="user",
                    character_id="luotianyi",
                    context_summary="unverifiable summary",
                    context_memory_count=2,
                )
            )
            session.commit()

        state = service.get_call_conversation_seed_state("user", character_id="luotianyi", requested_at=REQUESTED_AT)

        assert state == {"summary": "", "conversations": [], "context_count": 0, "version": "0:0:"}
    finally:
        engine.dispose()
