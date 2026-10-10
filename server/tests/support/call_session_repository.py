"""Thread-safe in-memory implementation of the call-session repository port."""

from __future__ import annotations

import threading
from datetime import datetime
from uuid import UUID

from src.domain.call import CallState
from src.infrastructure.persistence.call_sessions import CallSessionRecord


class InMemoryCallSessionRepository:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_id: dict[UUID, CallSessionRecord] = {}
        self._request_ids: dict[str, UUID] = {}

    def create_if_absent(self, record: CallSessionRecord) -> CallSessionRecord:
        with self._lock:
            existing_id = self._request_ids.get(record.client_request_id)
            if existing_id is not None:
                existing = self._by_id[existing_id]
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
        with self._lock:
            current = self._by_id.get(call_id)
            if current is None or current.state is not expected_state:
                return False
            identity = (
                record.call_id,
                record.client_request_id,
                record.user_id,
                record.character_id,
                record.requested_at,
                record.created_at,
            )
            current_identity = (
                current.call_id,
                current.client_request_id,
                current.user_id,
                current.character_id,
                current.requested_at,
                current.created_at,
            )
            if identity != current_identity:
                raise ValueError("an update cannot change call identity")
            if record.updated_at < current.updated_at:
                raise ValueError("updated_at cannot move backwards")
            self._by_id[call_id] = record
            return True

    def list_stale(self, *, before: datetime, states: frozenset[CallState]) -> tuple[CallSessionRecord, ...]:
        with self._lock:
            return tuple(
                sorted(
                    (
                        record
                        for record in self._by_id.values()
                        if record.state in states and record.updated_at < before
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
