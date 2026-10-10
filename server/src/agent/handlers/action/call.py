"""Stage-directed realtime-call actions."""

import src.domain.agent as d
from src.agent.processing.output_emitter import OutputEmitter


class AnswerCallHandler:
    async def realize(
        self, action: d.Action, execution_context: d.ExecutionContext, outputs: OutputEmitter
    ) -> d.ActionResult:
        _ = execution_context, outputs
        if not isinstance(action, d.AnswerCall):
            raise TypeError("AnswerCallHandler requires AnswerCall")
        return _completed(action)


class EndCallHandler:
    async def realize(
        self, action: d.Action, execution_context: d.ExecutionContext, outputs: OutputEmitter
    ) -> d.ActionResult:
        _ = execution_context, outputs
        if not isinstance(action, d.EndCall):
            raise TypeError("EndCallHandler requires EndCall")
        return _completed(action)


def _completed(action: d.Action) -> d.ActionResult:
    return d.ActionResult(
        action_id=action.action_id,
        status=d.ActionExecutionStatus.COMPLETED,
        error_code=None,
        irreversible_effect_committed=False,
        effect_ref=None,
    )
