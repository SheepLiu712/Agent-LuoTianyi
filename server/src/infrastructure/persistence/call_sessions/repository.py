"""Persistence-neutral call ledger contract; no SQL schema is defined here."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Protocol
from uuid import UUID

from src.domain.call import CallEndReason, CallOutcome, CallState

BEIJING_TIMEZONE = timezone(timedelta(hours=8), name="Asia/Shanghai")
_DATETIME_FIELDS = (
    "requested_at",
    "created_at",
    "updated_at",
    "connected_at",
    "disconnected_at",
    "ended_at",
)


def normalize_call_datetime(value: datetime, *, field_name: str) -> datetime:
    """Require an aware instant and expose it at the fixed Beijing boundary."""
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(BEIJING_TIMEZONE)


class SettlementStatus(str, Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


STALE_RECOVERABLE_STATES = frozenset(
    {
        CallState.PREPARING,
        CallState.RINGING,
        CallState.ACTIVE,
        CallState.RECONNECTING,
        CallState.ENDING,
    }
)


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
        enum_values = (
            (self.state, CallState),
            (self.outcome, CallOutcome),
            (self.end_reason, CallEndReason),
            (self.summary_status, SettlementStatus),
            (self.maintenance_status, SettlementStatus),
        )
        if any(value is not None and not isinstance(value, enum_type) for value, enum_type in enum_values):
            raise ValueError("call session statuses must use the declared enum types")
        for field_name in _DATETIME_FIELDS:
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, normalize_call_datetime(value, field_name=field_name))

    def with_update(self, **changes: object) -> CallSessionRecord:
        return replace(self, **changes)


def validate_call_state_update(expected_state: CallState, new_state: CallState) -> None:
    """Reject only transitions that would revive a terminal ledger record."""
    if expected_state in {CallState.ENDED, CallState.FAILED} and new_state is not expected_state:
        raise ValueError(f"cannot transition terminal call state {expected_state.value}")
    if expected_state is CallState.DECLINED and new_state not in {CallState.DECLINED, CallState.ENDED}:
        raise ValueError("declined call state can only remain declined or settle to ended")


def validate_settlement_update(expected: SettlementStatus, new: SettlementStatus) -> None:
    """Allow first completion and an explicit failed-to-succeeded retry only."""
    if not isinstance(expected, SettlementStatus) or not isinstance(new, SettlementStatus):
        raise ValueError("settlement updates require declared status values")
    allowed = {
        SettlementStatus.PENDING: {SettlementStatus.SUCCEEDED, SettlementStatus.FAILED},
        SettlementStatus.FAILED: {SettlementStatus.SUCCEEDED},
        SettlementStatus.SUCCEEDED: set(),
    }
    if new not in allowed[expected]:
        raise ValueError(f"cannot transition settlement from {expected.value} to {new.value}")


def call_lifecycle_identity(record: CallSessionRecord) -> tuple[object, ...]:
    """Return durable identity fields owned by lifecycle CAS."""
    return (
        record.call_id,
        record.client_request_id,
        record.user_id,
        record.character_id,
        record.requested_at,
        record.created_at,
    )


def call_lifecycle_payload(record: CallSessionRecord) -> tuple[object, ...]:
    """Return lifecycle-owned facts, excluding settlement lanes and their shared timestamp."""
    return (
        *call_lifecycle_identity(record),
        record.state,
        record.outcome,
        record.end_reason,
        record.connected_at,
        record.disconnected_at,
        record.ended_at,
        record.active_duration_ms,
    )


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

    def update_summary_settlement(
        self,
        call_id: UUID,
        *,
        expected: SettlementStatus,
        new: SettlementStatus,
        conversation_id: UUID | None,
        updated_at: datetime,
    ) -> bool: ...

    def update_maintenance_settlement(
        self,
        call_id: UUID,
        *,
        expected: SettlementStatus,
        new: SettlementStatus,
        maintenance_turn_seq: int,
        updated_at: datetime,
    ) -> bool: ...

    def list_stale(self, *, before: datetime, states: frozenset[CallState]) -> tuple[CallSessionRecord, ...]: ...

    def delete_by_user(self, user_id: str) -> int: ...
