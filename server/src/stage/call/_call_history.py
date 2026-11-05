"""Persistence orchestration for Agent-produced call settlement results."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from src.domain.call import (
    CallContent,
    CallEndingResult,
    CallFinalSnapshot,
    CallOutcome,
    CallState,
    derive_call_conversation_id,
)
from src.domain.conversation_type import ConversationItem
from src.infrastructure.observability.call_metrics import CallMetric, CallMetricName, CallMetricResult, CallMetricStatus
from src.infrastructure.persistence.call_sessions import SettlementStatus
from src.utils.owned_operation import complete_owned

from ._call_conversation import validate_call_conversation_winner


class CallHistory:
    """保存通话结束结果，封装稳定身份及两个独立结果状态。"""

    def __init__(self, *, call_sessions, conversation_service, call_metrics=None):
        self._calls = call_sessions
        self._conversations = conversation_service
        self._call_metrics = call_metrics

    async def save(self, snapshot: CallFinalSnapshot, *, result: CallEndingResult | None) -> None:
        """写入概要和维护状态；等待两项写入均停止后再报告错误。"""
        record = await complete_owned(asyncio.to_thread(self._calls.find_by_id, snapshot.terminal.call_id))
        self._validate_record(record, snapshot)
        winner = await self._load_summary_winner(record)
        if record.outcome is CallOutcome.CONNECTED and result is None:
            raise ValueError("connected call requires an ending result")
        summary = winner if winner is not None else (result.summary if result else "")
        lanes = []
        if record.summary_status is not SettlementStatus.SUCCEEDED:
            lanes.append((CallMetricName.SUMMARY, self._settle_summary(record, summary)))
        if record.maintenance_status is not SettlementStatus.SUCCEEDED:
            succeeded = result is None or result.maintenance_succeeded
            progress = record.maintenance_turn_seq if result is None else result.maintenance_turn_seq
            lanes.append(
                (
                    CallMetricName.MAINTENANCE,
                    self._maintenance_cas(
                        record, SettlementStatus.SUCCEEDED if succeeded else SettlementStatus.FAILED, progress
                    ),
                )
            )
        outcomes = await asyncio.gather(*(operation for _, operation in lanes), return_exceptions=True)
        for (name, _), outcome in zip(lanes, outcomes):
            failed = isinstance(outcome, BaseException) or (
                name is CallMetricName.MAINTENANCE and result is not None and not result.maintenance_succeeded
            )
            self._record_metric(
                record.call_id,
                name,
                CallMetricResult.FAILED if failed else CallMetricResult.SUCCEEDED,
                status=CallMetricStatus.ERROR if failed else CallMetricStatus.SUCCESS,
            )
        errors = [outcome for outcome in outcomes if isinstance(outcome, BaseException)]
        if errors:
            raise errors[0]

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
                await self._summary_cas(record, SettlementStatus.FAILED, None)
                raise
        await self._summary_cas(record, SettlementStatus.SUCCEEDED, conversation_id)

    async def _summary_cas(self, record, new, conversation_id) -> None:
        current = await complete_owned(asyncio.to_thread(self._calls.find_by_id, record.call_id))
        if current.summary_status in {SettlementStatus.SUCCEEDED, new}:
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
        if current.maintenance_status in {SettlementStatus.SUCCEEDED, new}:
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
