"""SQLAlchemy implementation of the durable call-session ledger."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from sqlalchemy import case, delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.domain.call import CallEndReason, CallOutcome, CallState
from src.infrastructure.persistence.call_sessions.repository import (
    BEIJING_TIMEZONE,
    STALE_RECOVERABLE_STATES,
    CallSessionRecord,
    SettlementStatus,
    call_lifecycle_identity,
    call_lifecycle_payload,
    normalize_call_datetime,
    validate_call_state_update,
    validate_settlement_update,
)
from src.infrastructure.persistence.database.sql_database import CallSession


def _stored_time(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return normalize_call_datetime(value, field_name="ledger datetime").replace(tzinfo=None)


def _record_time(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        raise ValueError("SQLite call-session timestamps must be naive Beijing values")
    return value.replace(tzinfo=BEIJING_TIMEZONE)


def _to_record(row: CallSession) -> CallSessionRecord:
    return CallSessionRecord(
        call_id=UUID(row.call_id),
        client_request_id=row.client_request_id,
        user_id=row.user_id,
        character_id=row.character_id,
        state=CallState(row.state),
        outcome=CallOutcome(row.outcome) if row.outcome else None,
        end_reason=CallEndReason(row.end_reason) if row.end_reason else None,
        requested_at=_record_time(row.requested_at),
        connected_at=_record_time(row.connected_at),
        disconnected_at=_record_time(row.disconnected_at),
        ended_at=_record_time(row.ended_at),
        active_duration_ms=row.active_duration_ms,
        summary_status=SettlementStatus(row.summary_status),
        maintenance_status=SettlementStatus(row.maintenance_status),
        conversation_id=UUID(row.conversation_id) if row.conversation_id else None,
        maintenance_turn_seq=row.maintenance_turn_seq,
        created_at=_record_time(row.created_at),
        updated_at=_record_time(row.updated_at),
    )


def _values(record: CallSessionRecord) -> dict[str, object]:
    return {
        "call_id": str(record.call_id),
        "client_request_id": record.client_request_id,
        "user_id": record.user_id,
        "character_id": record.character_id,
        "state": record.state.value,
        "outcome": record.outcome.value if record.outcome else None,
        "end_reason": record.end_reason.value if record.end_reason else None,
        "requested_at": _stored_time(record.requested_at),
        "connected_at": _stored_time(record.connected_at),
        "disconnected_at": _stored_time(record.disconnected_at),
        "ended_at": _stored_time(record.ended_at),
        "active_duration_ms": record.active_duration_ms,
        "summary_status": record.summary_status.value,
        "maintenance_status": record.maintenance_status.value,
        "conversation_id": str(record.conversation_id) if record.conversation_id else None,
        "maintenance_turn_seq": record.maintenance_turn_seq,
        "created_at": _stored_time(record.created_at),
        "updated_at": _stored_time(record.updated_at),
    }


class SqlCallSessionRepository:
    """Atomic SQLite-backed implementation of ``CallSessionRepository``."""

    def __init__(self, sql_session_factory: Callable[[], Session]) -> None:
        self._sql_session_factory = sql_session_factory

    def create_if_absent(self, record: CallSessionRecord) -> CallSessionRecord:
        session = self._sql_session_factory()
        try:
            session.add(CallSession(**_values(record)))
            try:
                session.commit()
                return record
            except IntegrityError:
                session.rollback()
                return self._resolve_create_conflict(session, record)
        finally:
            session.close()

    @staticmethod
    def _resolve_create_conflict(session: Session, record: CallSessionRecord) -> CallSessionRecord:
        request_match = session.scalar(
            select(CallSession).where(CallSession.client_request_id == record.client_request_id)
        )
        id_match = session.get(CallSession, str(record.call_id))
        if request_match is not None and id_match is not None and request_match.call_id != id_match.call_id:
            raise ValueError("call identity conflicts across request and call_id")
        if request_match is not None:
            existing = _to_record(request_match)
            if existing.user_id != record.user_id or existing.character_id != record.character_id:
                raise ValueError("client_request_id belongs to another call owner")
            return existing
        if id_match is not None:
            existing = _to_record(id_match)
            if existing != record:
                raise ValueError("call_id already exists with different content")
            return existing
        raise RuntimeError("call session insert failed without an identity conflict")

    def find_by_id(self, call_id: UUID) -> CallSessionRecord | None:
        session = self._sql_session_factory()
        try:
            row = session.get(CallSession, str(call_id))
            return _to_record(row) if row is not None else None
        finally:
            session.close()

    def find_by_request(self, client_request_id: str) -> CallSessionRecord | None:
        session = self._sql_session_factory()
        try:
            row = session.scalar(select(CallSession).where(CallSession.client_request_id == client_request_id))
            return _to_record(row) if row is not None else None
        finally:
            session.close()

    def update_if_state(
        self,
        call_id: UUID,
        *,
        expected_state: CallState,
        record: CallSessionRecord,
    ) -> bool:
        if record.call_id != call_id:
            raise ValueError("an update cannot change call identity")
        validate_call_state_update(expected_state, record.state)
        session = self._sql_session_factory()
        try:
            lifecycle_values = _values(record)
            for field in ("summary_status", "maintenance_status", "conversation_id", "maintenance_turn_seq"):
                lifecycle_values.pop(field)
            stored_updated_at = lifecycle_values.pop("updated_at")
            result = session.execute(
                update(CallSession)
                .where(
                    CallSession.call_id == str(call_id),
                    CallSession.state == expected_state.value,
                    CallSession.client_request_id == record.client_request_id,
                    CallSession.user_id == record.user_id,
                    CallSession.character_id == record.character_id,
                    CallSession.requested_at == _stored_time(record.requested_at),
                    CallSession.created_at == _stored_time(record.created_at),
                    CallSession.updated_at < stored_updated_at,
                )
                .values(
                    **lifecycle_values,
                    updated_at=case(
                        (CallSession.updated_at < stored_updated_at, stored_updated_at),
                        else_=CallSession.updated_at,
                    ),
                )
            )
            if result.rowcount == 1:
                session.commit()
                return True
            session.rollback()
            return self._resolve_lifecycle_cas_miss(session, call_id, record)
        finally:
            session.close()

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
        values: dict[str, object] = {
            "summary_status": new.value,
            "conversation_id": str(conversation_id) if conversation_id else None,
        }
        return self._update_settlement(
            call_id,
            status_column=CallSession.summary_status,
            expected=expected,
            updated_at=updated_at,
            values=values,
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
        values: dict[str, object] = {"maintenance_status": new.value}
        extra_where: tuple[object, ...] = ()
        if new is SettlementStatus.SUCCEEDED:
            values["maintenance_turn_seq"] = maintenance_turn_seq
            extra_where = (CallSession.maintenance_turn_seq <= maintenance_turn_seq,)
        return self._update_settlement(
            call_id,
            status_column=CallSession.maintenance_status,
            expected=expected,
            updated_at=updated_at,
            values=values,
            extra_where=extra_where,
        )

    def _update_settlement(
        self,
        call_id: UUID,
        *,
        status_column: object,
        expected: SettlementStatus,
        updated_at: datetime,
        values: dict[str, object],
        extra_where: tuple[object, ...] = (),
    ) -> bool:
        stored_updated_at = _stored_time(updated_at)
        session = self._sql_session_factory()
        try:
            result = session.execute(
                update(CallSession)
                .where(
                    CallSession.call_id == str(call_id),
                    CallSession.state == CallState.ENDED.value,
                    status_column == expected.value,
                    *extra_where,
                )
                .values(
                    **values,
                    updated_at=case(
                        (CallSession.updated_at < stored_updated_at, stored_updated_at),
                        else_=CallSession.updated_at,
                    ),
                )
            )
            if result.rowcount == 1:
                session.commit()
                return True
            session.rollback()
            return False
        finally:
            session.close()

    @staticmethod
    def _resolve_lifecycle_cas_miss(
        session: Session,
        call_id: UUID,
        record: CallSessionRecord,
    ) -> bool:
        row = session.get(CallSession, str(call_id))
        if row is None:
            return False
        current = _to_record(row)
        if call_lifecycle_identity(record) != call_lifecycle_identity(current):
            raise ValueError("an update cannot change call identity")
        return record.updated_at <= current.updated_at and call_lifecycle_payload(record) == call_lifecycle_payload(
            current
        )

    def list_stale(self, *, before: datetime, states: frozenset[CallState]) -> tuple[CallSessionRecord, ...]:
        before = normalize_call_datetime(before, field_name="before")
        query_states = states & STALE_RECOVERABLE_STATES
        if not query_states:
            return ()
        session = self._sql_session_factory()
        try:
            rows = session.scalars(
                select(CallSession)
                .where(
                    CallSession.state.in_(state.value for state in query_states),
                    CallSession.updated_at < _stored_time(before),
                )
                .order_by(CallSession.updated_at, CallSession.call_id)
            ).all()
            return tuple(_to_record(row) for row in rows)
        finally:
            session.close()

    def delete_by_user(self, user_id: str) -> int:
        session = self._sql_session_factory()
        try:
            result = session.execute(delete(CallSession).where(CallSession.user_id == user_id))
            session.commit()
            return result.rowcount
        finally:
            session.close()
