"""SQLite evidence for the durable call-session repository."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import fields
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from src.domain.call import CallEndReason, CallOutcome, CallState
from src.infrastructure.persistence.call_sessions import (
    BEIJING_TIMEZONE,
    CallSessionRecord,
    SettlementStatus,
    SqlCallSessionRepository,
)
from src.infrastructure.persistence.database.sql_database import Base, CallSession, init_sql_db


def _sessions(database_path):
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine), engine


def _record(*, call_id=None, request_id="request-1", user_id="user", character_id="luotianyi", updated_at=None):
    now = datetime.now(timezone.utc)
    return CallSessionRecord(
        call_id=call_id or uuid4(),
        client_request_id=request_id,
        user_id=user_id,
        character_id=character_id,
        state=CallState.PREPARING,
        requested_at=now,
        created_at=now,
        updated_at=updated_at or now,
    )


def _same_instant_offsets():
    instant = datetime(2026, 1, 1, 0, 30, tzinfo=timezone.utc)
    return instant, instant.astimezone(timezone(timedelta(hours=-5))), instant.astimezone(timezone(timedelta(hours=9)))


def test_two_sql_sessions_with_different_call_ids_converge_on_request_winner(tmp_path):
    sessions, engine = _sessions(tmp_path / "calls.db")
    repository = SqlCallSessionRepository(sessions)
    contenders = (_record(), _record())

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(repository.create_if_absent, contenders))

    assert results[0] == results[1]
    assert results[0] in contenders
    with sessions() as session:
        assert session.query(CallSession).count() == 1
    engine.dispose()


def test_create_rejects_request_owner_and_call_identity_conflicts(tmp_path):
    sessions, engine = _sessions(tmp_path / "conflicts.db")
    repository = SqlCallSessionRepository(sessions)
    original = _record()
    repository.create_if_absent(original)

    with pytest.raises(ValueError, match="another call owner"):
        repository.create_if_absent(_record(request_id=original.client_request_id, user_id="other"))
    assert repository.create_if_absent(_record(request_id=original.client_request_id)) == original
    with pytest.raises(ValueError, match="call_id already exists"):
        repository.create_if_absent(_record(call_id=original.call_id, request_id="other-request"))
    assert repository.find_by_id(original.call_id) == original
    engine.dispose()


def test_sql_create_rejects_crossed_request_and_call_id_matches_without_pollution(tmp_path):
    sessions, engine = _sessions(tmp_path / "crossed-identity.db")
    repository = SqlCallSessionRepository(sessions)
    first = _record(request_id="request-a")
    second = _record(request_id="request-b")
    repository.create_if_absent(first)
    repository.create_if_absent(second)

    with pytest.raises(ValueError, match="identity conflicts"):
        repository.create_if_absent(_record(call_id=second.call_id, request_id=first.client_request_id))

    assert repository.find_by_request("request-a") == first
    assert repository.find_by_request("request-b") == second
    with sessions() as session:
        assert session.query(CallSession).count() == 2
    engine.dispose()


def test_expected_state_compare_and_swap_has_one_winner(tmp_path):
    sessions, engine = _sessions(tmp_path / "cas.db")
    repository = SqlCallSessionRepository(sessions)
    original = _record()
    repository.create_if_absent(original)
    changed_at = original.updated_at + timedelta(seconds=1)
    active = original.with_update(state=CallState.ACTIVE, connected_at=changed_at, updated_at=changed_at)
    ringing = original.with_update(state=CallState.RINGING, updated_at=changed_at)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                repository.update_if_state,
                original.call_id,
                expected_state=CallState.PREPARING,
                record=candidate,
            )
            for candidate in (active, ringing)
        ]
    assert sorted(future.result() for future in futures) == [False, True]
    assert repository.find_by_id(original.call_id).state in {CallState.ACTIVE, CallState.RINGING}
    engine.dispose()


def test_sql_lifecycle_stale_candidate_cannot_overwrite_newer_facts(tmp_path):
    sessions, engine = _sessions(tmp_path / "stale-lifecycle.db")
    repository = SqlCallSessionRepository(sessions)
    original = _record().with_update(
        state=CallState.ACTIVE,
        connected_at=datetime.now(timezone.utc),
        active_duration_ms=20,
    )
    repository.create_if_absent(original)
    newer = original.with_update(
        disconnected_at=original.updated_at + timedelta(seconds=2),
        active_duration_ms=40,
        updated_at=original.updated_at + timedelta(seconds=2),
    )
    assert repository.update_if_state(original.call_id, expected_state=CallState.ACTIVE, record=newer)
    stale = original.with_update(
        disconnected_at=original.updated_at + timedelta(seconds=1),
        active_duration_ms=30,
        updated_at=original.updated_at + timedelta(seconds=1),
    )

    assert not repository.update_if_state(original.call_id, expected_state=CallState.ACTIVE, record=stale)
    assert repository.find_by_id(original.call_id) == newer
    engine.dispose()


def test_sql_lifecycle_same_timestamp_has_one_payload_winner_and_idempotent_retry(tmp_path):
    sessions, engine = _sessions(tmp_path / "same-time-lifecycle.db")
    repository = SqlCallSessionRepository(sessions)
    original = _record()
    repository.create_if_absent(original)
    changed_at = original.updated_at + timedelta(seconds=1)
    candidates = (
        original.with_update(state=CallState.ACTIVE, active_duration_ms=10, updated_at=changed_at),
        original.with_update(state=CallState.RINGING, active_duration_ms=20, updated_at=changed_at),
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                repository.update_if_state,
                original.call_id,
                expected_state=CallState.PREPARING,
                record=candidate,
            )
            for candidate in candidates
        ]

    assert sorted(future.result() for future in futures) == [False, True]
    winner = repository.find_by_id(original.call_id)
    assert winner in candidates
    assert repository.update_if_state(
        original.call_id,
        expected_state=CallState.PREPARING,
        record=winner,
    )
    loser = candidates[0] if winner == candidates[1] else candidates[1]
    assert not repository.update_if_state(
        original.call_id,
        expected_state=CallState.PREPARING,
        record=loser,
    )
    assert repository.find_by_id(original.call_id) == winner
    engine.dispose()


def test_sql_lifecycle_idempotency_ignores_independent_settlement_fields(tmp_path):
    sessions, engine = _sessions(tmp_path / "lifecycle-settlement-idempotency.db")
    repository = SqlCallSessionRepository(sessions)
    original = _record()
    repository.create_if_absent(original)
    candidate = original.with_update(state=CallState.ENDED, updated_at=original.updated_at + timedelta(seconds=1))
    assert repository.update_if_state(original.call_id, expected_state=CallState.PREPARING, record=candidate)
    assert repository.update_summary_settlement(
        original.call_id,
        expected=SettlementStatus.PENDING,
        new=SettlementStatus.SUCCEEDED,
        conversation_id=uuid4(),
        updated_at=candidate.updated_at + timedelta(seconds=1),
    )

    assert repository.update_if_state(original.call_id, expected_state=CallState.PREPARING, record=candidate)
    engine.dispose()


@pytest.mark.parametrize("terminal_state", [CallState.ENDED, CallState.FAILED])
def test_sql_terminal_state_cannot_revive(tmp_path, terminal_state):
    sessions, engine = _sessions(tmp_path / f"terminal-{terminal_state.value}.db")
    repository = SqlCallSessionRepository(sessions)
    original = _record().with_update(state=terminal_state)
    repository.create_if_absent(original)

    with pytest.raises(ValueError, match="terminal call state"):
        repository.update_if_state(
            original.call_id,
            expected_state=terminal_state,
            record=original.with_update(state=CallState.ACTIVE),
        )
    engine.dispose()


def test_sql_generic_lifecycle_update_cannot_change_settlement_fields(tmp_path):
    sessions, engine = _sessions(tmp_path / "generic-settlement.db")
    repository = SqlCallSessionRepository(sessions)
    original = _record()
    repository.create_if_absent(original)

    candidate = original.with_update(
        state=CallState.RINGING,
        summary_status=SettlementStatus.FAILED,
        updated_at=original.updated_at + timedelta(seconds=1),
    )
    assert repository.update_if_state(
        original.call_id,
        expected_state=CallState.PREPARING,
        record=candidate,
    )
    updated = repository.find_by_id(original.call_id)
    assert updated.state is CallState.RINGING
    assert updated.summary_status is SettlementStatus.PENDING
    engine.dispose()


def test_two_sql_settlement_lanes_both_succeed_without_lost_update(tmp_path):
    sessions, engine = _sessions(tmp_path / "parallel-settlement.db")
    repository = SqlCallSessionRepository(sessions)
    original = _record().with_update(state=CallState.ENDED)
    repository.create_if_absent(original)
    conversation_id = uuid4()

    with ThreadPoolExecutor(max_workers=2) as pool:
        summary = pool.submit(
            repository.update_summary_settlement,
            original.call_id,
            expected=SettlementStatus.PENDING,
            new=SettlementStatus.SUCCEEDED,
            conversation_id=conversation_id,
            updated_at=original.updated_at + timedelta(seconds=2),
        )
        maintenance = pool.submit(
            repository.update_maintenance_settlement,
            original.call_id,
            expected=SettlementStatus.PENDING,
            new=SettlementStatus.SUCCEEDED,
            maintenance_turn_seq=9,
            updated_at=original.updated_at + timedelta(seconds=1),
        )

    assert summary.result() is True
    assert maintenance.result() is True
    settled = repository.find_by_id(original.call_id)
    assert settled.state is CallState.ENDED
    assert settled.summary_status is SettlementStatus.SUCCEEDED
    assert settled.conversation_id == conversation_id
    assert settled.maintenance_status is SettlementStatus.SUCCEEDED
    assert settled.maintenance_turn_seq == 9
    assert settled.updated_at == original.updated_at + timedelta(seconds=2)
    engine.dispose()


def test_sql_settlement_retry_and_cas_semantics(tmp_path):
    sessions, engine = _sessions(tmp_path / "settlement-retry.db")
    repository = SqlCallSessionRepository(sessions)
    original = _record().with_update(state=CallState.ENDED)
    repository.create_if_absent(original)
    failed_at = original.updated_at + timedelta(seconds=2)

    assert repository.update_summary_settlement(
        original.call_id,
        expected=SettlementStatus.PENDING,
        new=SettlementStatus.FAILED,
        conversation_id=None,
        updated_at=failed_at,
    )
    assert not repository.update_summary_settlement(
        original.call_id,
        expected=SettlementStatus.PENDING,
        new=SettlementStatus.SUCCEEDED,
        conversation_id=uuid4(),
        updated_at=original.updated_at + timedelta(seconds=1),
    )
    conversation_id = uuid4()
    assert repository.update_summary_settlement(
        original.call_id,
        expected=SettlementStatus.FAILED,
        new=SettlementStatus.SUCCEEDED,
        conversation_id=conversation_id,
        updated_at=original.updated_at + timedelta(seconds=1),
    )
    settled = repository.find_by_id(original.call_id)
    assert settled.summary_status is SettlementStatus.SUCCEEDED
    assert settled.conversation_id == conversation_id
    assert settled.updated_at == failed_at
    with pytest.raises(ValueError, match="cannot transition settlement"):
        repository.update_summary_settlement(
            original.call_id,
            expected=SettlementStatus.SUCCEEDED,
            new=SettlementStatus.FAILED,
            conversation_id=None,
            updated_at=failed_at,
        )
    engine.dispose()


def test_sql_parallel_settlement_same_lane_has_one_cas_winner(tmp_path):
    sessions, engine = _sessions(tmp_path / "same-lane-cas.db")
    repository = SqlCallSessionRepository(sessions)
    original = _record().with_update(state=CallState.ENDED)
    repository.create_if_absent(original)
    candidates = (uuid4(), uuid4())

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                repository.update_summary_settlement,
                original.call_id,
                expected=SettlementStatus.PENDING,
                new=SettlementStatus.SUCCEEDED,
                conversation_id=conversation_id,
                updated_at=original.updated_at + timedelta(seconds=1),
            )
            for conversation_id in candidates
        ]

    assert sorted(future.result() for future in futures) == [False, True]
    settled = repository.find_by_id(original.call_id)
    assert settled.summary_status is SettlementStatus.SUCCEEDED
    assert settled.conversation_id in candidates
    engine.dispose()


@pytest.mark.parametrize(
    "state",
    [
        CallState.PREPARING,
        CallState.RINGING,
        CallState.ACTIVE,
        CallState.RECONNECTING,
        CallState.ENDING,
        CallState.FAILED,
        CallState.DECLINED,
    ],
)
def test_sql_settlement_lanes_only_run_for_ended_records(tmp_path, state):
    sessions, engine = _sessions(tmp_path / f"settlement-state-{state.value}.db")
    repository = SqlCallSessionRepository(sessions)
    original = _record().with_update(state=state)
    repository.create_if_absent(original)

    assert not repository.update_summary_settlement(
        original.call_id,
        expected=SettlementStatus.PENDING,
        new=SettlementStatus.SUCCEEDED,
        conversation_id=uuid4(),
        updated_at=original.updated_at + timedelta(seconds=1),
    )
    assert not repository.update_maintenance_settlement(
        original.call_id,
        expected=SettlementStatus.PENDING,
        new=SettlementStatus.SUCCEEDED,
        maintenance_turn_seq=3,
        updated_at=original.updated_at + timedelta(seconds=1),
    )
    assert repository.find_by_id(original.call_id) == original
    engine.dispose()


def test_sql_failed_maintenance_does_not_advance_and_success_requires_nonregressing_progress(tmp_path):
    sessions, engine = _sessions(tmp_path / "maintenance-progress.db")
    repository = SqlCallSessionRepository(sessions)
    original = _record().with_update(state=CallState.ENDED, maintenance_turn_seq=5)
    repository.create_if_absent(original)

    assert repository.update_maintenance_settlement(
        original.call_id,
        expected=SettlementStatus.PENDING,
        new=SettlementStatus.FAILED,
        maintenance_turn_seq=99,
        updated_at=original.updated_at + timedelta(seconds=1),
    )
    assert repository.find_by_id(original.call_id).maintenance_turn_seq == 5
    assert not repository.update_maintenance_settlement(
        original.call_id,
        expected=SettlementStatus.FAILED,
        new=SettlementStatus.SUCCEEDED,
        maintenance_turn_seq=4,
        updated_at=original.updated_at + timedelta(seconds=2),
    )
    assert repository.update_maintenance_settlement(
        original.call_id,
        expected=SettlementStatus.FAILED,
        new=SettlementStatus.SUCCEEDED,
        maintenance_turn_seq=6,
        updated_at=original.updated_at + timedelta(seconds=2),
    )
    assert repository.find_by_id(original.call_id).maintenance_turn_seq == 6
    engine.dispose()


@pytest.mark.parametrize("conversation_id", ["not-a-uuid", 1, True])
def test_sql_summary_rejects_non_uuid_conversation_id_without_mutation(tmp_path, conversation_id):
    sessions, engine = _sessions(tmp_path / f"bad-conversation-{conversation_id}.db")
    repository = SqlCallSessionRepository(sessions)
    original = _record().with_update(state=CallState.ENDED)
    repository.create_if_absent(original)

    with pytest.raises(ValueError, match="conversation_id"):
        repository.update_summary_settlement(
            original.call_id,
            expected=SettlementStatus.PENDING,
            new=SettlementStatus.SUCCEEDED,
            conversation_id=conversation_id,
            updated_at=original.updated_at + timedelta(seconds=1),
        )
    assert repository.find_by_id(original.call_id) == original
    engine.dispose()


def test_sql_declined_state_only_remains_declined_or_settles_to_ended(tmp_path):
    sessions, engine = _sessions(tmp_path / "declined.db")
    repository = SqlCallSessionRepository(sessions)
    original = _record().with_update(state=CallState.DECLINED)
    repository.create_if_absent(original)

    with pytest.raises(ValueError, match="declined call state"):
        repository.update_if_state(
            original.call_id,
            expected_state=CallState.DECLINED,
            record=original.with_update(state=CallState.ACTIVE),
        )
    ended = original.with_update(state=CallState.ENDED, updated_at=original.updated_at + timedelta(seconds=1))
    assert repository.update_if_state(original.call_id, expected_state=CallState.DECLINED, record=ended)
    engine.dispose()


@pytest.mark.parametrize(
    "changes",
    [
        {"client_request_id": "other-request"},
        {"user_id": "other-user"},
        {"character_id": "other-character"},
        {"requested_at": datetime(2026, 1, 1, tzinfo=timezone.utc)},
        {"created_at": datetime(2026, 1, 1, tzinfo=timezone.utc)},
    ],
)
def test_sql_update_cannot_change_identity(tmp_path, changes):
    sessions, engine = _sessions(tmp_path / "identity.db")
    repository = SqlCallSessionRepository(sessions)
    original = _record()
    repository.create_if_absent(original)

    with pytest.raises(ValueError, match="identity"):
        repository.update_if_state(
            original.call_id,
            expected_state=CallState.PREPARING,
            record=original.with_update(state=CallState.ACTIVE, **changes),
        )
    assert repository.find_by_id(original.call_id) == original
    engine.dispose()


def test_round_trip_stale_terminal_filter_delete_and_reopen(tmp_path):
    database = tmp_path / "lifecycle.db"
    sessions, engine = _sessions(database)
    repository = SqlCallSessionRepository(sessions)
    old_time = datetime.now(timezone.utc) - timedelta(minutes=5)
    active = _record(updated_at=old_time).with_update(
        state=CallState.ACTIVE,
        outcome=CallOutcome.CONNECTED,
        connected_at=old_time,
        active_duration_ms=1234,
        summary_status=SettlementStatus.FAILED,
        maintenance_status=SettlementStatus.SUCCEEDED,
        maintenance_turn_seq=7,
    )
    ended = _record(request_id="ended", updated_at=old_time).with_update(
        state=CallState.ENDED,
        outcome=CallOutcome.CANCELLED_BEFORE_ANSWER,
        end_reason=CallEndReason.USER_HANGUP,
        ended_at=old_time,
    )
    other = _record(request_id="other", user_id="other")
    for record in (active, ended, other):
        repository.create_if_absent(record)

    assert repository.list_stale(
        before=datetime.now(timezone.utc),
        states=frozenset({CallState.ACTIVE, CallState.ENDED}),
    ) == (active,)
    assert repository.delete_by_user("user") == 2
    assert repository.find_by_id(other.call_id) == other
    engine.dispose()

    reopened_sessions, reopened_engine = _sessions(database)
    reopened = SqlCallSessionRepository(reopened_sessions)
    assert reopened.find_by_request("other") == other
    reopened_engine.dispose()


def test_sql_round_trip_normalizes_same_instant_offsets_to_fixed_beijing(tmp_path):
    sessions, engine = _sessions(tmp_path / "offsets.db")
    repository = SqlCallSessionRepository(sessions)
    utc, west, east = _same_instant_offsets()
    record = CallSessionRecord(
        call_id=uuid4(),
        client_request_id="offset-request",
        user_id="user",
        character_id="luotianyi",
        state=CallState.ACTIVE,
        requested_at=utc,
        connected_at=west,
        disconnected_at=east,
        ended_at=utc,
        created_at=west,
        updated_at=east,
    )

    stored = repository.create_if_absent(record)
    loaded = repository.find_by_id(record.call_id)

    assert loaded == stored
    for field_name in ("requested_at", "connected_at", "disconnected_at", "ended_at", "created_at", "updated_at"):
        value = getattr(loaded, field_name)
        assert value.tzinfo is BEIJING_TIMEZONE
        assert value.utcoffset() == timedelta(hours=8)
    with sessions() as session:
        row = session.get(CallSession, str(record.call_id))
        assert row.requested_at == datetime(2026, 1, 1, 8, 30)
        assert row.connected_at == datetime(2026, 1, 1, 8, 30)
    engine.dispose()


def test_sql_reopen_preserves_beijing_boundary_and_same_instant_stale_query(tmp_path):
    database = tmp_path / "beijing-reopen.db"
    sessions, engine = _sessions(database)
    repository = SqlCallSessionRepository(sessions)
    utc, west, _east = _same_instant_offsets()
    record = _record(updated_at=west).with_update(requested_at=utc, created_at=utc)
    repository.create_if_absent(record)
    engine.dispose()

    reopened_sessions, reopened_engine = _sessions(database)
    reopened = SqlCallSessionRepository(reopened_sessions)
    loaded = reopened.find_by_id(record.call_id)
    assert loaded.updated_at == datetime(2026, 1, 1, 8, 30, tzinfo=BEIJING_TIMEZONE)
    assert reopened.list_stale(
        before=datetime(2026, 1, 1, 8, 31, tzinfo=BEIJING_TIMEZONE),
        states=frozenset({CallState.PREPARING}),
    ) == (loaded,)
    assert (
        reopened.list_stale(
            before=datetime(2025, 12, 31, 19, 30, tzinfo=timezone(timedelta(hours=-5))),
            states=frozenset({CallState.PREPARING}),
        )
        == ()
    )
    reopened_engine.dispose()


def test_sql_time_conversion_never_calls_implicit_datetime_astimezone(tmp_path):
    sessions, engine = _sessions(tmp_path / "no-host-timezone.db")
    repository = SqlCallSessionRepository(sessions)

    class ExplicitOffset(datetime):
        def astimezone(self, tz=None):
            if tz is None:
                raise AssertionError("implicit host timezone conversion is forbidden")
            return super().astimezone(tz)

    instant = ExplicitOffset(2026, 1, 1, 0, 30, tzinfo=timezone.utc)
    record = _record(updated_at=instant).with_update(requested_at=instant, created_at=instant)

    repository.create_if_absent(record)
    assert repository.list_stale(
        before=ExplicitOffset(2026, 1, 1, 0, 31, tzinfo=timezone.utc),
        states=frozenset({CallState.PREPARING}),
    ) == (record,)
    engine.dispose()


def test_sql_identity_and_cas_compare_same_instants_across_offsets(tmp_path):
    sessions, engine = _sessions(tmp_path / "offset-cas.db")
    repository = SqlCallSessionRepository(sessions)
    utc, west, east = _same_instant_offsets()
    original = _record(updated_at=utc).with_update(requested_at=utc, created_at=utc)
    repository.create_if_absent(original)
    changed = original.with_update(
        state=CallState.RINGING,
        requested_at=west,
        created_at=east,
        updated_at=utc + timedelta(seconds=1),
    )

    assert repository.update_if_state(
        original.call_id,
        expected_state=CallState.PREPARING,
        record=changed,
    )
    loaded = repository.find_by_id(original.call_id)
    assert loaded.requested_at == original.requested_at
    assert loaded.created_at == original.created_at
    assert loaded.updated_at == datetime(2026, 1, 1, 8, 30, 1, tzinfo=BEIJING_TIMEZONE)
    engine.dispose()


@pytest.mark.parametrize(
    "field_name",
    ["requested_at", "created_at", "updated_at", "connected_at", "disconnected_at", "ended_at"],
)
def test_record_rejects_naive_datetime_for_every_public_time_field(field_name):
    aware = datetime(2026, 1, 1, tzinfo=BEIJING_TIMEZONE)
    values = {
        "requested_at": aware,
        "created_at": aware,
        "updated_at": aware,
        "connected_at": None,
        "disconnected_at": None,
        "ended_at": None,
    }
    values[field_name] = datetime(2026, 1, 1)

    with pytest.raises(ValueError, match=f"{field_name} must be timezone-aware"):
        CallSessionRecord(
            call_id=uuid4(),
            client_request_id=f"naive-{field_name}",
            user_id="user",
            character_id="luotianyi",
            state=CallState.PREPARING,
            **values,
        )


def test_sql_stale_cutoff_rejects_naive_datetime_without_host_conversion(tmp_path):
    sessions, engine = _sessions(tmp_path / "naive-cutoff.db")
    repository = SqlCallSessionRepository(sessions)
    repository.create_if_absent(_record())

    with pytest.raises(ValueError, match="before must be timezone-aware"):
        repository.list_stale(before=datetime(2026, 1, 1), states=frozenset({CallState.PREPARING}))
    engine.dispose()


def test_schema_is_privacy_allowlisted_and_has_nonnegative_constraints(tmp_path):
    sessions, engine = _sessions(tmp_path / "privacy.db")
    columns = {column["name"] for column in inspect(engine).get_columns("call_sessions")}
    record_fields = {field.name for field in fields(CallSessionRecord)}
    assert columns == record_fields
    assert not columns.intersection({"pcm", "audio", "transcript", "summary", "working_summary", "context"})

    invalid = _record()
    with sessions() as session:
        session.add(
            CallSession(
                **{
                    "call_id": str(invalid.call_id),
                    "client_request_id": invalid.client_request_id,
                    "user_id": invalid.user_id,
                    "character_id": invalid.character_id,
                    "state": invalid.state.value,
                    "requested_at": invalid.requested_at.replace(tzinfo=None),
                    "active_duration_ms": -1,
                    "summary_status": SettlementStatus.PENDING.value,
                    "maintenance_status": SettlementStatus.PENDING.value,
                    "maintenance_turn_seq": -1,
                    "created_at": invalid.created_at.replace(tzinfo=None),
                    "updated_at": invalid.updated_at.replace(tzinfo=None),
                }
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
    engine.dispose()


def test_init_adds_call_table_to_old_database_and_is_repeatable(tmp_path):
    database = tmp_path / "legacy.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE legacy_marker (value VARCHAR PRIMARY KEY)")
        connection.execute("INSERT INTO legacy_marker VALUES ('preserved')")

    init_sql_db(str(tmp_path), database.name)
    init_sql_db(str(tmp_path), database.name)

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT value FROM legacy_marker").fetchone() == ("preserved",)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(call_sessions)")}
        indexes = {row[1] for row in connection.execute("PRAGMA index_list(call_sessions)")}
    assert columns == {field.name for field in fields(CallSessionRecord)}
    assert {"ix_call_sessions_stale", "ix_call_sessions_user_id"}.issubset(indexes)
