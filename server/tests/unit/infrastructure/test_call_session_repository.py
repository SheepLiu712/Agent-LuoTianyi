from dataclasses import fields
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from support.call_session_repository import InMemoryCallSessionRepository

from src.domain.call import CallState
from src.infrastructure.persistence.call_sessions import BEIJING_TIMEZONE, CallSessionRecord, SettlementStatus


def _record(*, call_id=None, request_id="request-1", user_id="user", updated_at=None):
    now = datetime.now(timezone.utc)
    return CallSessionRecord(
        call_id=call_id or uuid4(),
        client_request_id=request_id,
        user_id=user_id,
        character_id="luotianyi",
        state=CallState.PREPARING,
        requested_at=now,
        created_at=now,
        updated_at=updated_at or now,
    )


def test_ledger_record_excludes_audio_transcript_summary_and_working_context():
    names = {item.name for item in fields(CallSessionRecord)}
    assert not names.intersection({"pcm", "audio", "transcript", "summary", "working_summary", "context"})
    assert {"summary_status", "maintenance_status", "maintenance_turn_seq"}.issubset(names)


def test_create_is_idempotent_by_request_and_rejects_owner_conflict():
    repository = InMemoryCallSessionRepository()
    original = _record()
    assert repository.create_if_absent(original) is original
    repeated = _record(call_id=original.call_id)
    assert repository.create_if_absent(repeated) is original
    with pytest.raises(ValueError, match="another call owner"):
        repository.create_if_absent(_record(user_id="other"))
    assert repository.create_if_absent(_record()) is original


def test_create_rejects_crossed_request_and_call_id_matches_without_pollution():
    repository = InMemoryCallSessionRepository()
    first = _record(request_id="request-a")
    second = _record(request_id="request-b")
    repository.create_if_absent(first)
    repository.create_if_absent(second)

    with pytest.raises(ValueError, match="identity conflicts"):
        repository.create_if_absent(_record(call_id=second.call_id, request_id=first.client_request_id))

    assert repository.find_by_request("request-a") == first
    assert repository.find_by_request("request-b") == second


def test_expected_state_update_stale_query_and_user_delete():
    repository = InMemoryCallSessionRepository()
    old = _record(updated_at=datetime.now(timezone.utc) - timedelta(minutes=5))
    other = _record(request_id="request-2", user_id="other")
    repository.create_if_absent(old)
    repository.create_if_absent(other)
    active = old.with_update(state=CallState.ACTIVE, updated_at=datetime.now(timezone.utc))

    assert not repository.update_if_state(old.call_id, expected_state=CallState.RINGING, record=active)
    assert repository.update_if_state(old.call_id, expected_state=CallState.PREPARING, record=active)
    assert repository.find_by_id(old.call_id) == active
    assert repository.find_by_request(old.client_request_id) == active
    assert repository.list_stale(
        before=datetime.now(timezone.utc) + timedelta(seconds=1), states=frozenset({CallState.ACTIVE})
    ) == (active,)
    assert repository.delete_by_user("user") == 1
    assert repository.find_by_id(old.call_id) is None
    assert repository.find_by_id(other.call_id) == other


def test_stale_query_intersects_shared_recoverable_states():
    repository = InMemoryCallSessionRepository()
    old_time = datetime.now(timezone.utc) - timedelta(minutes=5)
    active = _record(updated_at=old_time).with_update(state=CallState.ACTIVE)
    ended = _record(request_id="ended", updated_at=old_time).with_update(state=CallState.ENDED)
    repository.create_if_absent(active)
    repository.create_if_absent(ended)

    assert repository.list_stale(
        before=datetime.now(timezone.utc),
        states=frozenset({CallState.ACTIVE, CallState.ENDED}),
    ) == (active,)


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
def test_update_cannot_change_durable_identity(changes):
    repository = InMemoryCallSessionRepository()
    original = _record()
    repository.create_if_absent(original)

    with pytest.raises(ValueError, match="identity"):
        repository.update_if_state(
            original.call_id,
            expected_state=CallState.PREPARING,
            record=original.with_update(state=CallState.ACTIVE, **changes),
        )


def test_lifecycle_update_rejects_stale_candidate_without_overwriting_newer_facts():
    repository = InMemoryCallSessionRepository()
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


def test_fake_lifecycle_same_timestamp_is_idempotent_only_for_same_payload():
    repository = InMemoryCallSessionRepository()
    original = _record()
    repository.create_if_absent(original)
    changed_at = original.updated_at + timedelta(seconds=1)
    winner = original.with_update(state=CallState.ACTIVE, active_duration_ms=10, updated_at=changed_at)
    conflict = original.with_update(state=CallState.RINGING, active_duration_ms=20, updated_at=changed_at)

    assert repository.update_if_state(original.call_id, expected_state=CallState.PREPARING, record=winner)
    assert repository.update_if_state(original.call_id, expected_state=CallState.PREPARING, record=winner)
    assert not repository.update_if_state(original.call_id, expected_state=CallState.PREPARING, record=conflict)
    assert repository.find_by_id(original.call_id) == winner


def test_fake_lifecycle_idempotency_ignores_independent_settlement_fields():
    repository = InMemoryCallSessionRepository()
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


def test_generic_lifecycle_update_cannot_change_settlement_fields():
    repository = InMemoryCallSessionRepository()
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


def test_fake_summary_and_maintenance_updates_do_not_overwrite_each_other():
    repository = InMemoryCallSessionRepository()
    original = _record().with_update(state=CallState.ENDED)
    repository.create_if_absent(original)
    conversation_id = uuid4()
    summary_time = original.updated_at + timedelta(seconds=2)
    maintenance_time = original.updated_at + timedelta(seconds=1)

    assert repository.update_summary_settlement(
        original.call_id,
        expected=SettlementStatus.PENDING,
        new=SettlementStatus.SUCCEEDED,
        conversation_id=conversation_id,
        updated_at=summary_time,
    )
    assert repository.update_maintenance_settlement(
        original.call_id,
        expected=SettlementStatus.PENDING,
        new=SettlementStatus.SUCCEEDED,
        maintenance_turn_seq=7,
        updated_at=maintenance_time,
    )

    settled = repository.find_by_id(original.call_id)
    assert settled.state is CallState.ENDED
    assert settled.summary_status is SettlementStatus.SUCCEEDED
    assert settled.conversation_id == conversation_id
    assert settled.maintenance_status is SettlementStatus.SUCCEEDED
    assert settled.maintenance_turn_seq == 7
    assert settled.updated_at == summary_time
    assert not repository.update_summary_settlement(
        original.call_id,
        expected=SettlementStatus.PENDING,
        new=SettlementStatus.FAILED,
        conversation_id=None,
        updated_at=summary_time,
    )


def test_fake_failed_settlement_can_retry_to_success_but_success_cannot_regress():
    repository = InMemoryCallSessionRepository()
    original = _record().with_update(state=CallState.ENDED)
    repository.create_if_absent(original)
    failed_at = original.updated_at + timedelta(seconds=1)
    success_at = original.updated_at + timedelta(seconds=2)

    assert repository.update_summary_settlement(
        original.call_id,
        expected=SettlementStatus.PENDING,
        new=SettlementStatus.FAILED,
        conversation_id=None,
        updated_at=failed_at,
    )
    conversation_id = uuid4()
    assert repository.update_summary_settlement(
        original.call_id,
        expected=SettlementStatus.FAILED,
        new=SettlementStatus.SUCCEEDED,
        conversation_id=conversation_id,
        updated_at=success_at,
    )
    with pytest.raises(ValueError, match="cannot transition settlement"):
        repository.update_summary_settlement(
            original.call_id,
            expected=SettlementStatus.SUCCEEDED,
            new=SettlementStatus.FAILED,
            conversation_id=None,
            updated_at=success_at,
        )


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
def test_fake_settlement_lanes_only_run_for_ended_records(state):
    repository = InMemoryCallSessionRepository()
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


def test_fake_failed_maintenance_does_not_advance_progress_and_success_never_regresses_it():
    repository = InMemoryCallSessionRepository()
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


@pytest.mark.parametrize("conversation_id", ["not-a-uuid", 1, True])
def test_fake_summary_rejects_non_uuid_conversation_id_without_mutation(conversation_id):
    repository = InMemoryCallSessionRepository()
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


def test_fake_failed_summary_requires_none_conversation_id():
    repository = InMemoryCallSessionRepository()
    original = _record().with_update(state=CallState.ENDED)
    repository.create_if_absent(original)

    with pytest.raises(ValueError, match="failed summary settlement"):
        repository.update_summary_settlement(
            original.call_id,
            expected=SettlementStatus.PENDING,
            new=SettlementStatus.FAILED,
            conversation_id=uuid4(),
            updated_at=original.updated_at + timedelta(seconds=1),
        )
    assert repository.find_by_id(original.call_id) == original


@pytest.mark.parametrize("turn_seq", [True, 1.5, "1"])
def test_fake_maintenance_rejects_non_integer_progress(turn_seq):
    repository = InMemoryCallSessionRepository()
    original = _record().with_update(state=CallState.ENDED)
    repository.create_if_absent(original)

    with pytest.raises(ValueError, match="maintenance_turn_seq"):
        repository.update_maintenance_settlement(
            original.call_id,
            expected=SettlementStatus.PENDING,
            new=SettlementStatus.SUCCEEDED,
            maintenance_turn_seq=turn_seq,
            updated_at=original.updated_at + timedelta(seconds=1),
        )
    assert repository.find_by_id(original.call_id) == original


@pytest.mark.parametrize("terminal_state", [CallState.ENDED, CallState.FAILED])
def test_terminal_state_cannot_be_revived_and_generic_update_cannot_settle(terminal_state):
    repository = InMemoryCallSessionRepository()
    original = _record().with_update(state=terminal_state)
    repository.create_if_absent(original)

    with pytest.raises(ValueError, match="terminal call state"):
        repository.update_if_state(
            original.call_id,
            expected_state=terminal_state,
            record=original.with_update(state=CallState.ACTIVE),
        )
    settled = original.with_update(summary_status=SettlementStatus.SUCCEEDED)
    assert repository.update_if_state(original.call_id, expected_state=terminal_state, record=settled)
    assert repository.find_by_id(original.call_id).summary_status is SettlementStatus.PENDING


def test_declined_state_can_only_remain_declined_or_settle_to_ended():
    repository = InMemoryCallSessionRepository()
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


def test_record_rejects_naive_datetime_at_public_ledger_boundary():
    naive = datetime(2026, 1, 1)
    with pytest.raises(ValueError, match="requested_at must be timezone-aware"):
        CallSessionRecord(
            call_id=uuid4(),
            client_request_id="naive-request",
            user_id="user",
            character_id="luotianyi",
            state=CallState.PREPARING,
            requested_at=naive,
            created_at=naive,
            updated_at=naive,
        )


def test_record_normalizes_all_aware_datetimes_to_fixed_beijing_offset():
    instant = datetime(2026, 1, 1, tzinfo=timezone.utc)
    record = _record(updated_at=instant).with_update(
        requested_at=instant,
        created_at=instant,
        connected_at=instant,
        disconnected_at=instant,
        ended_at=instant,
    )

    for field_name in (
        "requested_at",
        "created_at",
        "updated_at",
        "connected_at",
        "disconnected_at",
        "ended_at",
    ):
        value = getattr(record, field_name)
        assert value.tzinfo is BEIJING_TIMEZONE
        assert value.hour == 8


def test_in_memory_stale_cutoff_rejects_naive_datetime():
    repository = InMemoryCallSessionRepository()
    repository.create_if_absent(_record())

    with pytest.raises(ValueError, match="before must be timezone-aware"):
        repository.list_stale(before=datetime(2026, 1, 1), states=frozenset({CallState.PREPARING}))
