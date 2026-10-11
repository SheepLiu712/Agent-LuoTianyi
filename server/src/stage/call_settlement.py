"""Stage-owned execution of the two call settlement Agent lanes."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

import src.domain.agent as d
from src.domain.call import CallAgentSettlementResult, CallFinalSnapshot, CallState
from src.infrastructure.persistence.call_sessions import CallSessionRecord


class CallAgentSettlement:
    def __init__(self, *, get_agent, get_context_factory) -> None:
        self._get_agent = get_agent
        self._get_context_factory = get_context_factory

    async def settle(
        self,
        record: CallSessionRecord,
        snapshot: CallFinalSnapshot,
        *,
        skip_summary: bool = False,
        settlement_input_digest: str,
    ) -> CallAgentSettlementResult:
        context = await self._get_context_factory(record.character_id).create_call(
            str(record.call_id), user_id=record.user_id, requested_at=record.requested_at.replace(tzinfo=None)
        )
        try:
            plans = _PlanSink()
            request = _request(record, snapshot, settlement_input_digest)
            report = await self._get_agent(record.character_id).handle_stimulus(request, plans, context=context)
            if report.request_status is not d.HandlingRequestStatus.COMPLETED or len(plans.plans) != 1:
                raise RuntimeError("Agent did not produce one call settlement plan")
            summary_action, maintenance_action = plans.plans[0].actions
            summary_task = (
                asyncio.sleep(0, result=None)
                if skip_summary
                else self._realize_one(record, summary_action, plans.plans[0], context)
            )
            summary, maintenance = await asyncio.gather(
                summary_task,
                self._realize_maintenance_with_retry(record, maintenance_action, plans.plans[0], context),
                return_exceptions=True,
            )
            return CallAgentSettlementResult(
                summary="" if skip_summary else _effect_or_error(summary, d.EffectKind.CALL_SUMMARY),
                maintenance_turn_seq=_turn_or_error(maintenance),
            )
        finally:
            await context.close()

    async def _realize_maintenance_with_retry(self, record, action, plan, context):
        try:
            return await self._realize_one(record, action, plan, context)
        except Exception:
            return await self._realize_one(record, action, plan, context)

    async def _realize_one(self, record, action, source_plan, context):
        plan = d.ActionPlan(
            plan_id=f"plan-v1-{uuid4().hex}",
            origin_request_id=source_plan.origin_request_id,
            plan_ordinal=source_plan.plan_ordinal,
            target_character_id=source_plan.target_character_id,
            interaction_id=source_plan.interaction_id,
            basis_interaction_revision=source_plan.basis_interaction_revision,
            source_stimulus_ids=source_plan.source_stimulus_ids,
            actions=(action,),
        )
        execution = d.ExecutionContext(
            execution_id=str(uuid4()),
            interaction_id=str(record.call_id),
            current_interaction_revision=0,
            cancellation=d.CancellationToken(),
            interaction_context=context,
        )
        report = await self._get_agent(record.character_id).realize_action_plan(plan, execution, _OutputSink())
        if report.status is not d.ExecutionStatus.COMPLETED:
            raise RuntimeError("call settlement action failed")
        return report.action_results[0]


class _PlanSink:
    def __init__(self) -> None:
        self.plans = []

    async def emit(self, plan):
        self.plans.append(plan)
        return d.PlanReceipt(plan_id=plan.plan_id, status=d.PlanAcceptanceStatus.ACCEPTED)


class _OutputSink:
    async def emit(self, output):
        raise d.SinkRejectedError("call settlement cannot emit output", code=d.SinkRejectionCode.UNSUPPORTED_OUTPUT)


def _request(record, snapshot, settlement_input_digest):
    now = datetime.now(timezone.utc)
    stimulus = d.CallSettlementRequested(
        stimulus_id=str(uuid4()),
        schema_version=1,
        occurred_at=now,
        source=d.StimulusSource.STAGE,
        target_character_ids=(record.character_id,),
        user_id=record.user_id,
        ephemeral=True,
        call_id=record.call_id,
        final_snapshot=snapshot,
        settlement_input_digest=settlement_input_digest,
    )
    interaction = d.CallInteractionSnapshot(
        interaction_id=str(record.call_id),
        interaction_revision=0,
        user_id=record.user_id,
        pending_stimuli=(),
        now=now,
        timezone=ZoneInfo("Asia/Shanghai"),
        supported_outputs=frozenset(d.AgentOutputKind),
        call_id=record.call_id,
        state=CallState.ENDED,
        connection_state=d.ConnectionState.DISCONNECTED,
    )
    return d.HandleStimulusRequest(
        request_id=str(uuid4()), stimulus=stimulus, interaction=interaction, cancellation=d.CancellationToken()
    )


def _effect_or_error(result, kind):
    if isinstance(result, BaseException):
        return result
    if result.effect_ref is None or result.effect_ref.kind is not kind:
        return RuntimeError("call settlement effect is missing")
    return result.effect_ref.effect_id


def _turn_or_error(result):
    value = _effect_or_error(result, d.EffectKind.CALL_MAINTENANCE)
    if isinstance(value, BaseException):
        return value
    return int(value)
