"""Persistence orchestration for Agent-produced call settlement results."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from src.domain.call import (
    CallContent,
    CallFinalSnapshot,
    CallOutcome,
    CallState,
    call_settlement_input_digest,
    derive_call_conversation_id,
)
from src.domain.conversation_type import ConversationItem
from src.infrastructure.observability.call_metrics import CallMetric, CallMetricName, CallMetricResult, CallMetricStatus
from src.infrastructure.persistence.call_sessions import CallSessionRepository, SettlementStatus
from src.utils.owned_operation import complete_owned

from .conversation_projection import validate_call_conversation_winner


class CallAgentSettlementPort:
    async def settle(self, record, snapshot): ...


class CallSettlementConsumerImpl:
    def __init__(
        self,
        *,
        agent_settlement: CallAgentSettlementPort,
        call_sessions: CallSessionRepository,
        conversation_service: object,
        release_call_maintenance=None,
        call_maintenance_batches=None,
        call_metrics=None,
    ) -> None:
        self._agent_settlement = agent_settlement
        self._calls = call_sessions
        self._conversations = conversation_service
        self._release_call_maintenance = release_call_maintenance
        self._batches = call_maintenance_batches
        self._call_metrics = call_metrics

    async def settle(self, snapshot: CallFinalSnapshot) -> None:
        record = await complete_owned(asyncio.to_thread(self._calls.find_by_id, snapshot.terminal.call_id))
        self._validate_record(record, snapshot)
        digest = call_settlement_input_digest(snapshot)
        claimed = await complete_owned(
            asyncio.to_thread(self._calls.claim_settlement_input, record.call_id, digest=digest)
        )
        if not claimed:
            raise RuntimeError("settlement input claim failed")
        record = await complete_owned(asyncio.to_thread(self._calls.find_by_id, record.call_id))
        await self._reconcile_completed_batches(record, digest)
        if self._settled(record):
            return
        try:
            await self._settle_record(record, snapshot, digest)
        finally:
            if self._release_call_maintenance is not None:
                self._release_call_maintenance(record.call_id)

    def _record_metric(self, call_id, name, result, *, status=CallMetricStatus.SUCCESS) -> None:
        if self._call_metrics is None:
            return
        now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        self._call_metrics.record(
            CallMetric(
                call_id=call_id,
                name=name,
                start_ts=now,
                end_ts=now,
                duration_ms=0,
                status=status,
                labels={"result": result.value},
            )
        )

    async def _settle_record(self, record, snapshot, digest) -> None:
        winner = await self._load_summary_winner(record)
        if record.outcome is not CallOutcome.CONNECTED:
            if record.summary_status is not SettlementStatus.SUCCEEDED:
                await self._settle_summary(record, winner if winner is not None else "")
            if record.maintenance_status is not SettlementStatus.SUCCEEDED:
                await self._maintenance_cas(record, SettlementStatus.SUCCEEDED, record.maintenance_turn_seq)
            return
        result = await self._agent_settlement.settle(
            record, snapshot, skip_summary=winner is not None, settlement_input_digest=digest
        )
        lanes = []
        if record.summary_status is not SettlementStatus.SUCCEEDED:
            lanes.append(self._settle_summary(record, winner if winner is not None else result.summary))
        if record.maintenance_status is not SettlementStatus.SUCCEEDED:
            lanes.append(self._settle_maintenance(record, result.maintenance_turn_seq))
        outcomes = await asyncio.gather(*lanes, return_exceptions=True)
        for name, outcome in zip(
            (
                name
                for name, required in (
                    (CallMetricName.SUMMARY, record.summary_status is not SettlementStatus.SUCCEEDED),
                    (CallMetricName.MAINTENANCE, record.maintenance_status is not SettlementStatus.SUCCEEDED),
                )
                if required
            ),
            outcomes,
        ):
            self._record_metric(
                record.call_id,
                name,
                CallMetricResult.FAILED if isinstance(outcome, BaseException) else CallMetricResult.SUCCEEDED,
                status=CallMetricStatus.ERROR if isinstance(outcome, BaseException) else CallMetricStatus.SUCCESS,
            )
        errors = [outcome for outcome in outcomes if isinstance(outcome, BaseException)]
        if errors:
            raise errors[0]

    @staticmethod
    def _settled(record) -> bool:
        return (
            record.summary_status is SettlementStatus.SUCCEEDED
            and record.maintenance_status is SettlementStatus.SUCCEEDED
        )

    @staticmethod
    def _validate_record(record, snapshot) -> None:
        if record is None or record.state is not CallState.ENDED:
            raise RuntimeError("settlement requires an ENDED call ledger")
        if record.outcome is not snapshot.terminal.outcome or record.end_reason is not snapshot.terminal.end_reason:
            raise RuntimeError("settlement snapshot does not match durable terminal facts")
        if record.active_duration_ms != snapshot.terminal.active_duration_ms:
            raise RuntimeError("settlement duration does not match durable terminal facts")

    async def _load_summary_winner(self, record) -> str | None:
        conversation_id = derive_call_conversation_id(
            user_id=record.user_id, character_id=record.character_id, call_id=record.call_id
        )
        item = await complete_owned(
            asyncio.to_thread(
                self._conversations.get_call_conversation,
                str(conversation_id),
                user_id=record.user_id,
                character_id=record.character_id,
            )
        )
        if item is None:
            return None
        return validate_call_conversation_winner(record, item)

    async def _settle_summary(self, record, summary) -> None:
        if isinstance(summary, BaseException):
            await self._summary_cas(record, SettlementStatus.FAILED, None)
            raise summary
        content = CallContent(
            call_id=record.call_id,
            outcome=record.outcome,
            active_duration_ms=record.active_duration_ms,
            summary=summary if record.outcome is CallOutcome.CONNECTED else None,
            end_reason=record.end_reason,
        )
        conversation_id = derive_call_conversation_id(
            user_id=record.user_id, character_id=record.character_id, call_id=record.call_id
        )
        item = ConversationItem(
            uuid=str(conversation_id),
            timestamp=record.requested_at.replace(tzinfo=None).isoformat(sep=" ", timespec="microseconds"),
            source="user",
            type="call",
            content=content.render_for_agent(),
            data={
                "call_id": str(record.call_id),
                "outcome": record.outcome.value,
                "active_duration_ms": record.active_duration_ms,
                "summary": content.summary,
                "end_reason": record.end_reason.value,
            },
        )
        try:
            await complete_owned(
                asyncio.to_thread(self._conversations.add_call_conversation, record.user_id, record.character_id, item)
            )
        except Exception:
            winner = await self._load_summary_winner(record)
            if winner is None:
                raise
        await self._summary_cas(record, SettlementStatus.SUCCEEDED, conversation_id)

    async def _settle_maintenance(self, record, turn_seq) -> None:
        if isinstance(turn_seq, BaseException):
            await self._maintenance_cas(record, SettlementStatus.FAILED, record.maintenance_turn_seq)
            raise turn_seq
        await self._maintenance_cas(record, SettlementStatus.SUCCEEDED, turn_seq)
        if self._batches is not None and turn_seq > record.maintenance_turn_seq:
            batch = await complete_owned(
                asyncio.to_thread(
                    self._batches.load,
                    call_id=record.call_id,
                    user_id=record.user_id,
                    character_id=record.character_id,
                    previous_turn_seq=record.maintenance_turn_seq,
                    target_turn_seq=turn_seq,
                )
            )
            if batch is not None:
                await complete_owned(asyncio.to_thread(self._batches.mark_completed, batch.maintenance_id))

    async def _reconcile_completed_batches(self, record, digest) -> None:
        if self._batches is None or record.maintenance_turn_seq <= 0:
            return
        batches = await complete_owned(
            asyncio.to_thread(
                self._batches.list_for_call,
                call_id=record.call_id,
                user_id=record.user_id,
                character_id=record.character_id,
            )
        )
        for batch in batches:
            if (
                batch.status == "frozen"
                and batch.target_turn_seq <= record.maintenance_turn_seq
                and batch.settlement_input_digest == digest
            ):
                await complete_owned(asyncio.to_thread(self._batches.mark_completed, batch.maintenance_id))

    async def _summary_cas(self, record, new, conversation_id) -> None:
        current = await complete_owned(asyncio.to_thread(self._calls.find_by_id, record.call_id))
        if current.summary_status is SettlementStatus.SUCCEEDED:
            return
        changed = await complete_owned(
            asyncio.to_thread(
                self._calls.update_summary_settlement,
                record.call_id,
                expected=current.summary_status,
                new=new,
                conversation_id=conversation_id,
                updated_at=datetime.now(timezone.utc),
            )
        )
        if not changed:
            raise RuntimeError("summary settlement CAS failed")

    async def _maintenance_cas(self, record, new, turn_seq) -> None:
        current = await complete_owned(asyncio.to_thread(self._calls.find_by_id, record.call_id))
        if current.maintenance_status is SettlementStatus.SUCCEEDED:
            return
        changed = await complete_owned(
            asyncio.to_thread(
                self._calls.update_maintenance_settlement,
                record.call_id,
                expected=current.maintenance_status,
                new=new,
                maintenance_turn_seq=turn_seq,
                updated_at=datetime.now(timezone.utc),
            )
        )
        if not changed:
            raise RuntimeError("maintenance settlement CAS failed")
