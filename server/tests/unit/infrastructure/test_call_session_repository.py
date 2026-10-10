from dataclasses import fields
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from support.call_session_repository import InMemoryCallSessionRepository

from src.domain.call import CallState
from src.infrastructure.persistence.call_sessions import CallSessionRecord


def _record(*, request_id="request-1", user_id="user", updated_at=None):
    now = datetime.now(timezone.utc)
    return CallSessionRecord(
        call_id=uuid4(),
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
    repeated = _record()
    assert repository.create_if_absent(repeated) is original
    with pytest.raises(ValueError, match="another call owner"):
        repository.create_if_absent(_record(user_id="other"))


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


def test_update_timestamp_cannot_move_backwards():
    repository = InMemoryCallSessionRepository()
    original = _record()
    repository.create_if_absent(original)

    with pytest.raises(ValueError, match="backwards"):
        repository.update_if_state(
            original.call_id,
            expected_state=CallState.PREPARING,
            record=original.with_update(
                state=CallState.ACTIVE,
                updated_at=original.updated_at - timedelta(microseconds=1),
            ),
        )
