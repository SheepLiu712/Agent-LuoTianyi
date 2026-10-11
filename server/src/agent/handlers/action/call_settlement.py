"""Real Agent actions for summary and call-only cognitive maintenance."""

import src.domain.agent as d
from src.agent.context import UserProfile
from src.agent.processing.output_emitter import OutputEmitter
from src.agent.skills.cognitive.call_settlement import CallMaintenanceSkill, CallSummarySkill
from src.agent.skills.invocation import execution_invocation


class SummarizeCallHandler:
    def __init__(self, character_id: str, skill: CallSummarySkill) -> None:
        self._character_id, self._skill = character_id, skill

    async def realize(self, action: d.Action, context: d.ExecutionContext, outputs: OutputEmitter) -> d.ActionResult:
        if not isinstance(action, d.SummarizeCall):
            raise TypeError("SummarizeCallHandler requires SummarizeCall")
        summary = await self._skill.summarize(
            execution_invocation(self._character_id, context, user_id=action.user_id),
            action.final_snapshot,
        )
        return _result(action, effect_ref=d.EffectRef(kind=d.EffectKind.CALL_SUMMARY, effect_id=summary))


class MaintainCallHandler:
    def __init__(self, character_id: str, skill: CallMaintenanceSkill) -> None:
        self._character_id, self._skill = character_id, skill

    async def realize(self, action: d.Action, context: d.ExecutionContext, outputs: OutputEmitter) -> d.ActionResult:
        if not isinstance(action, d.MaintainCall):
            raise TypeError("MaintainCallHandler requires MaintainCall")
        if context.interaction_context is None:
            raise RuntimeError("call maintenance requires interaction context")
        profile = context.interaction_context.user.read().profile.description
        turn_seq, proposed_profile = await self._skill.maintain(
            execution_invocation(self._character_id, context, user_id=action.user_id),
            action.final_snapshot,
            current_profile=profile,
            settlement_input_digest=action.settlement_input_digest,
        )
        if proposed_profile is not None:
            await context.interaction_context.user.update_profile(UserProfile(description=proposed_profile))
        return _result(
            action,
            effect_ref=d.EffectRef(kind=d.EffectKind.CALL_MAINTENANCE, effect_id=str(turn_seq)),
        )


def _result(action: d.Action, *, effect_ref: d.EffectRef) -> d.ActionResult:
    return d.ActionResult(
        action_id=action.action_id,
        status=d.ActionExecutionStatus.COMPLETED,
        error_code=None,
        irreversible_effect_committed=True,
        effect_ref=effect_ref,
    )
