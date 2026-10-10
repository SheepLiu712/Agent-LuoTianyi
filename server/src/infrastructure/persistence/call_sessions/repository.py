"""Persistence-neutral call ledger contract; no SQL schema is defined here."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from typing import Protocol
from uuid import UUID

from src.domain.call import CallEndReason, CallOutcome, CallState


class SettlementStatus(str, Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class CallSessionRecord:
    """Privacy allowlist for durable call lifecycle and settlement facts."""

    call_id: UUID
    client_request_id: str
    user_id: str
    character_id: str
    state: CallState
    requested_at: datetime
    created_at: datetime
    updated_at: datetime
    outcome: CallOutcome | None = None
    end_reason: CallEndReason | None = None
    connected_at: datetime | None = None
    disconnected_at: datetime | None = None
    ended_at: datetime | None = None
    active_duration_ms: int = 0
    summary_status: SettlementStatus = SettlementStatus.PENDING
    maintenance_status: SettlementStatus = SettlementStatus.PENDING
    conversation_id: UUID | None = None
    maintenance_turn_seq: int = 0

    def __post_init__(self) -> None:
        if not self.client_request_id or not self.user_id or not self.character_id:
            raise ValueError("request, user, and character identities are required")
        if self.active_duration_ms < 0 or self.maintenance_turn_seq < 0:
            raise ValueError("durations and maintenance progress cannot be negative")

    def with_update(self, **changes: object) -> CallSessionRecord:
        return replace(self, **changes)


class CallSessionRepository(Protocol):
    def create_if_absent(self, record: CallSessionRecord) -> CallSessionRecord: ...

    def find_by_id(self, call_id: UUID) -> CallSessionRecord | None: ...

    def find_by_request(self, client_request_id: str) -> CallSessionRecord | None: ...

    def update_if_state(
        self,
        call_id: UUID,
        *,
        expected_state: CallState,
        record: CallSessionRecord,
    ) -> bool: ...

    def list_stale(self, *, before: datetime, states: frozenset[CallState]) -> tuple[CallSessionRecord, ...]: ...

    def delete_by_user(self, user_id: str) -> int: ...
