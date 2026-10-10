"""Thread-safe in-memory implementation of the call-session repository port."""

from __future__ import annotations

import threading
from datetime import datetime
from uuid import UUID

from src.domain.call import CallState
from src.infrastructure.persistence.call_sessions import (
    STALE_RECOVERABLE_STATES,
    CallSessionRecord,
    SettlementStatus,
    call_lifecycle_identity,
    call_lifecycle_payload,
    normalize_call_datetime,
)
from src.infrastructure.persistence.call_sessions.repository import (
    validate_call_state_update,
    validate_settlement_update,
)


class InMemoryCallSessionRepository:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_id: dict[UUID, CallSessionRecord] = {}
        self._request_ids: dict[str, UUID] = {}

    def create_if_absent(self, record: CallSessionRecord) -> CallSessionRecord:
        with self._lock:
            existing_id = self._request_ids.get(record.client_request_id)
            id_match = self._by_id.get(record.call_id)
            if existing_id is not None:
                existing = self._by_id[existing_id]
                if id_match is not None and id_match.call_id != existing.call_id:
                    raise ValueError("call identity conflicts across request and call_id")
                if existing.user_id != record.user_id or existing.character_id != record.character_id:
                    raise ValueError("client_request_id belongs to another call owner")
                return existing
            if record.call_id in self._by_id:
                existing = self._by_id[record.call_id]
                if existing != record:
                    raise ValueError("call_id already exists with different content")
                return existing
            self._by_id[record.call_id] = record
            self._request_ids[record.client_request_id] = record.call_id
            return record

    def find_by_id(self, call_id: UUID) -> CallSessionRecord | None:
        with self._lock:
            return self._by_id.get(call_id)

    def find_by_request(self, client_request_id: str) -> CallSessionRecord | None:
        with self._lock:
            call_id = self._request_ids.get(client_request_id)
            return self._by_id.get(call_id) if call_id is not None else None

    def update_if_state(
        self,
        call_id: UUID,
        *,
        expected_state: CallState,
        record: CallSessionRecord,
    ) -> bool:
        validate_call_state_update(expected_state, record.state)
        with self._lock:
            current = self._by_id.get(call_id)
            if current is None:
                return False
            if call_lifecycle_identity(record) != call_lifecycle_identity(current):
                raise ValueError("an update cannot change call identity")
            if record.updated_at <= current.updated_at and call_lifecycle_payload(record) == call_lifecycle_payload(
                current
            ):
                return True
            if current.state is not expected_state or record.updated_at <= current.updated_at:
                return False
            self._by_id[call_id] = record.with_update(
                summary_status=current.summary_status,
                maintenance_status=current.maintenance_status,
                conversation_id=current.conversation_id,
                maintenance_turn_seq=current.maintenance_turn_seq,
            )
            return True

    def update_summary_settlement(
        self,
        call_id: UUID,
        *,
        expected: SettlementStatus,
        new: SettlementStatus,
        conversation_id: UUID | None,
        updated_at: datetime,
    ) -> bool:
        validate_settlement_update(expected, new)
        if conversation_id is not None and not isinstance(conversation_id, UUID):
            raise ValueError("conversation_id must be UUID or None")
        if new is SettlementStatus.SUCCEEDED and conversation_id is None:
            raise ValueError("successful summary settlement requires conversation_id")
        if new is SettlementStatus.FAILED and conversation_id is not None:
            raise ValueError("failed summary settlement requires conversation_id None")
        return self._update_settlement(
            call_id,
            lane="summary",
            expected=expected,
            new=new,
            updated_at=updated_at,
            conversation_id=conversation_id,
        )

    def update_maintenance_settlement(
        self,
        call_id: UUID,
        *,
        expected: SettlementStatus,
        new: SettlementStatus,
        maintenance_turn_seq: int,
        updated_at: datetime,
    ) -> bool:
        validate_settlement_update(expected, new)
        if type(maintenance_turn_seq) is not int or maintenance_turn_seq < 0:
            raise ValueError("maintenance_turn_seq cannot be negative")
        changes = {}
        if new is SettlementStatus.SUCCEEDED:
            changes["maintenance_turn_seq"] = maintenance_turn_seq
        return self._update_settlement(
            call_id,
            lane="maintenance",
            expected=expected,
            new=new,
            updated_at=updated_at,
            **changes,
        )

    def _update_settlement(self, call_id, *, lane, expected, new, updated_at, **changes) -> bool:
        updated_at = normalize_call_datetime(updated_at, field_name="updated_at")
        with self._lock:
            current = self._by_id.get(call_id)
            if (
                current is None
                or current.state is not CallState.ENDED
                or getattr(current, f"{lane}_status") is not expected
            ):
                return False
            candidate_seq = changes.get("maintenance_turn_seq")
            if candidate_seq is not None and candidate_seq < current.maintenance_turn_seq:
                return False
            changes[f"{lane}_status"] = new
            changes["updated_at"] = max(current.updated_at, updated_at)
            self._by_id[call_id] = current.with_update(**changes)
            return True

    def list_stale(self, *, before: datetime, states: frozenset[CallState]) -> tuple[CallSessionRecord, ...]:
        before = normalize_call_datetime(before, field_name="before")
        with self._lock:
            return tuple(
                sorted(
                    (
                        record
                        for record in self._by_id.values()
                        if record.state in states & STALE_RECOVERABLE_STATES and record.updated_at < before
                    ),
                    key=lambda record: (record.updated_at, str(record.call_id)),
                )
            )

    def delete_by_user(self, user_id: str) -> int:
        with self._lock:
            call_ids = [call_id for call_id, record in self._by_id.items() if record.user_id == user_id]
            for call_id in call_ids:
                record = self._by_id.pop(call_id)
                self._request_ids.pop(record.client_request_id, None)
            return len(call_ids)
