"""Startup reconciliation for stale durable call ledgers."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Protocol
from uuid import UUID

from src.domain.call import CallContent, CallEndReason, CallOutcome, CallState, derive_call_conversation_id
from src.domain.conversation_type import ConversationItem
from src.infrastructure.persistence.call_sessions import (
    BEIJING_TIMEZONE,
    CallSessionRepository,
    SettlementStatus,
    normalize_call_datetime,
)
from src.utils.owned_operation import complete_owned

from .conversation_projection import validate_call_conversation_winner

INTERRUPTED_CALL_SUMMARY = "本次通话因服务中断，未能形成可用概要"


class CallMaintenanceProjectionVerificationPort(Protocol):
    def verify_completed_batch(self, batch) -> bool: ...


@dataclass(frozen=True, slots=True)
class CallRecoveryReport:
    scanned: int
    recovered: int
    skipped: int
    conflicted: int
    failed: int


class StaleCallRecoveryService:
    """Converge stale calls without reconstructing unavailable ephemeral input."""

    def __init__(
        self,
        *,
        call_sessions: CallSessionRepository,
        conversation_service: object,
        call_maintenance_batches: object,
        projection_verifier: CallMaintenanceProjectionVerificationPort,
        stale_after: timedelta = timedelta(seconds=30),
        wall_clock=None,
    ) -> None:
        if stale_after.total_seconds() < 0:
            raise ValueError("stale_after must be nonnegative")
        self._calls = call_sessions
        self._conversations = conversation_service
        self._batches = call_maintenance_batches
        self._projection_verifier = projection_verifier
        self._stale_after = stale_after
        self._wall_clock = wall_clock or (lambda: datetime.now(BEIJING_TIMEZONE))

    async def reconcile(self) -> CallRecoveryReport:
        now = normalize_call_datetime(self._wall_clock(), field_name="recovery wall clock")
        records = await self._owned(self._calls.list_recovery_pending, before=now - self._stale_after)
        recovered = skipped = conflicted = failed = 0
        for record in records:
            try:
                status = await self._recover_one(record, now)
            except Exception:
                failed += 1
            else:
                recovered += int(status == "recovered")
                conflicted += int(status == "conflicted")
                skipped += int(status == "skipped")
        return CallRecoveryReport(len(records), recovered, skipped, conflicted, failed)

    async def _recover_one(self, record, now: datetime) -> str:
        if record.state is CallState.ENDED:
            return await self._repair_claimed_terminal(record)
        if record.state in {CallState.PREPARING, CallState.RINGING}:
            failed = record.with_update(
                state=CallState.FAILED,
                end_reason=CallEndReason.SYSTEM_FAILURE,
                ended_at=now,
                updated_at=self._next_timestamp(record.updated_at, now),
            )
            changed = await self._owned(
                self._calls.update_if_state,
                record.call_id,
                expected_state=record.state,
                record=failed,
            )
            return "recovered" if changed else "conflicted"

        ended = record.with_update(
            state=CallState.ENDED,
            outcome=CallOutcome.CONNECTED,
            end_reason=CallEndReason.SYSTEM_FAILURE,
            ended_at=now,
            active_duration_ms=self._durable_duration(record),
            updated_at=self._next_timestamp(record.updated_at, now),
        )
        changed = await self._owned(
            self._calls.update_if_state,
            record.call_id,
            expected_state=record.state,
            record=ended,
        )
        current = await self._owned(self._calls.find_by_id, record.call_id)
        if current is None or current.state is not CallState.ENDED:
            return "conflicted"
        if current.end_reason is not CallEndReason.SYSTEM_FAILURE or current.outcome is not CallOutcome.CONNECTED:
            return "conflicted"
        status = await self._repair_claimed_terminal(current)
        return "recovered" if changed or status == "recovered" else status

    async def _repair_claimed_terminal(self, record) -> str:
        recovery_digest = recovery_settlement_digest(record)
        if record.settlement_input_digest is not None:
            repaired = await self._repair_normal_settlement(record, record.settlement_input_digest)
            return "recovered" if repaired else "skipped"
        try:
            claimed = await self._owned(self._calls.claim_settlement_input, record.call_id, digest=recovery_digest)
        except ValueError as error:
            if str(error) != "SETTLEMENT_INPUT_CONFLICT":
                raise
            current = await self._owned(self._calls.find_by_id, record.call_id)
            if current is None or current.settlement_input_digest is None:
                return "conflicted"
            repaired = await self._repair_normal_settlement(current, current.settlement_input_digest)
            return "recovered" if repaired else "skipped"
        if not claimed:
            return "conflicted"
        current = await self._owned(self._calls.find_by_id, record.call_id)
        if current.settlement_input_digest != recovery_digest:
            repaired = await self._repair_normal_settlement(current, current.settlement_input_digest)
            return "recovered" if repaired else "conflicted"
        await self._repair_recovery_projection(current, recovery_digest)
        return "recovered"

    async def _repair_recovery_projection(self, record, digest: str) -> None:
        conversation_id = derive_call_conversation_id(
            user_id=record.user_id,
            character_id=record.character_id,
            call_id=record.call_id,
        )
        winner = await self._load_winner(record, conversation_id)
        if winner is None:
            await self._persist_fallback(record, conversation_id)
        await self._repair_summary_status(record, conversation_id)
        await self._repair_maintenance_status(record, digest)

    async def _repair_normal_settlement(self, record, digest: str) -> bool:
        repaired = False
        conversation_id = derive_call_conversation_id(
            user_id=record.user_id,
            character_id=record.character_id,
            call_id=record.call_id,
        )
        winner = await self._load_winner(record, conversation_id)
        if winner is not None and record.summary_status is not SettlementStatus.SUCCEEDED:
            await self._repair_summary_status(record, conversation_id)
            repaired = True
        current = await self._owned(self._calls.find_by_id, record.call_id)
        completed = await self._verified_completed_batch(current, digest)
        if completed is not None and current.maintenance_status is not SettlementStatus.SUCCEEDED:
            await self._set_maintenance_status(current, SettlementStatus.SUCCEEDED, completed.target_turn_seq)
            repaired = True
        return repaired

    async def _load_winner(self, record, conversation_id) -> str | None:
        item = await self._owned(
            self._conversations.get_call_conversation,
            str(conversation_id),
            user_id=record.user_id,
            character_id=record.character_id,
        )
        return validate_call_conversation_winner(record, item)

    async def _persist_fallback(self, record, conversation_id) -> None:
        item = self._conversation_item(record, conversation_id)
        for attempt in range(3):
            try:
                await self._owned(self._conversations.add_call_conversation, record.user_id, record.character_id, item)
                return
            except Exception:
                winner = await self._load_winner(record, conversation_id)
                if winner is not None:
                    return
                if attempt == 2:
                    raise
                await asyncio.sleep(0.01 * (attempt + 1))

    async def _repair_summary_status(self, record, conversation_id) -> None:
        current = await self._owned(self._calls.find_by_id, record.call_id)
        if current.summary_status is SettlementStatus.SUCCEEDED:
            return
        changed = await self._owned(
            self._calls.update_summary_settlement,
            record.call_id,
            expected=current.summary_status,
            new=SettlementStatus.SUCCEEDED,
            conversation_id=conversation_id,
            updated_at=self._next_timestamp(current.updated_at, record.ended_at),
        )
        if not changed:
            current = await self._owned(self._calls.find_by_id, record.call_id)
            if current.summary_status is not SettlementStatus.SUCCEEDED:
                raise RuntimeError("stale summary recovery CAS failed")

    async def _repair_maintenance_status(self, record, digest: str) -> None:
        current = await self._owned(self._calls.find_by_id, record.call_id)
        if current.maintenance_status is SettlementStatus.SUCCEEDED:
            return
        completed = await self._verified_completed_batch(current, digest)
        new_status = SettlementStatus.SUCCEEDED if completed is not None else SettlementStatus.FAILED
        turn_seq = completed.target_turn_seq if completed is not None else current.maintenance_turn_seq
        if current.maintenance_status is SettlementStatus.FAILED and new_status is SettlementStatus.FAILED:
            return
        await self._set_maintenance_status(current, new_status, turn_seq)

    async def _set_maintenance_status(self, current, new_status, turn_seq) -> None:
        changed = await self._owned(
            self._calls.update_maintenance_settlement,
            current.call_id,
            expected=current.maintenance_status,
            new=new_status,
            maintenance_turn_seq=turn_seq,
            updated_at=self._next_timestamp(current.updated_at, current.ended_at),
        )
        if not changed:
            winner = await self._owned(self._calls.find_by_id, current.call_id)
            if (
                winner.maintenance_status is not SettlementStatus.SUCCEEDED
                and winner.maintenance_status is not new_status
            ):
                raise RuntimeError("stale maintenance recovery CAS failed")

    async def _verified_completed_batch(self, record, digest: str):
        batches = await self._owned(
            self._batches.list_for_call,
            call_id=record.call_id,
            user_id=record.user_id,
            character_id=record.character_id,
        )
        matching = [
            batch
            for batch in batches
            if batch.status == "completed"
            and batch.settlement_input_digest == digest
            and batch.previous_turn_seq == record.maintenance_turn_seq
        ]
        if len(matching) > 1:
            raise RuntimeError("multiple completed maintenance batches match recovery fence")
        if not matching:
            return None
        batch = matching[0]
        verified = await self._owned(self._projection_verifier.verify_completed_batch, batch)
        return batch if verified else None

    @staticmethod
    def _conversation_item(record, conversation_id: UUID) -> ConversationItem:
        content = CallContent(
            call_id=record.call_id,
            outcome=CallOutcome.CONNECTED,
            active_duration_ms=record.active_duration_ms,
            summary=INTERRUPTED_CALL_SUMMARY,
            end_reason=CallEndReason.SYSTEM_FAILURE,
        )
        return ConversationItem(
            uuid=str(conversation_id),
            timestamp=record.requested_at.replace(tzinfo=None).isoformat(sep=" ", timespec="microseconds"),
            source="user",
            type="call",
            content=content.render_for_agent(),
            data={
                "call_id": str(record.call_id),
                "outcome": CallOutcome.CONNECTED.value,
                "active_duration_ms": record.active_duration_ms,
                "summary": INTERRUPTED_CALL_SUMMARY,
                "end_reason": CallEndReason.SYSTEM_FAILURE.value,
            },
        )

    @staticmethod
    def _durable_duration(record) -> int:
        duration = record.active_duration_ms
        if record.connected_at is not None and record.disconnected_at is not None:
            duration = max(
                duration, int(max(0.0, (record.disconnected_at - record.connected_at).total_seconds()) * 1000)
            )
        return duration

    @staticmethod
    def _next_timestamp(previous: datetime, candidate: datetime | None) -> datetime:
        candidate = candidate or previous
        return candidate if candidate > previous else previous + timedelta(microseconds=1)

    @staticmethod
    async def _owned(operation, *args, **kwargs):
        return await complete_owned(asyncio.to_thread(operation, *args, **kwargs))


def recovery_settlement_digest(record) -> str:
    """Hash only stable durable terminal facts; exclude startup wall-clock timestamps."""
    payload = {
        "version": 1,
        "kind": "stale_recovery",
        "call_id": str(record.call_id),
        "user_id": record.user_id,
        "character_id": record.character_id,
        "requested_at": record.requested_at.isoformat(),
        "connected_at": record.connected_at.isoformat() if record.connected_at else None,
        "disconnected_at": record.disconnected_at.isoformat() if record.disconnected_at else None,
        "outcome": record.outcome.value,
        "end_reason": record.end_reason.value,
        "active_duration_ms": record.active_duration_ms,
        "maintenance_turn_seq": record.maintenance_turn_seq,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256(serialized.encode("utf-8")).hexdigest()
