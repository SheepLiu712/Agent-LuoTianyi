"""通过一次结束行动完成维护、概要生成和降级选择。"""

import src.domain.agent as d
from src.agent.skills.invocation import execution_invocation
from src.domain.call import CallEndingResult, CallSummarySource, fallback_call_summary
from src.utils.logger import get_logger


class FinalizeCallHandler:
    """维护失败不短路概要；模型重试由模型接口拥有。"""

    def __init__(self, character_id, maintenance, summary):
        self._character_id = character_id
        self._maintenance = maintenance
        self._summary = summary

    async def realize(self, action, context, outputs):
        if not isinstance(action, d.FinalizeCall):
            raise TypeError("FinalizeCallHandler requires FinalizeCall")
        interaction = context.interaction_context
        if interaction is None:
            raise RuntimeError("call ending requires its original context")
        invocation = execution_invocation(self._character_id, context, user_id=action.user_id)
        succeeded = True
        try:
            await self._maintenance.maintain_ending(invocation, interaction, action.final_snapshot)
        except Exception as error:
            succeeded = False
            get_logger(__name__).warning("Call maintenance failed type=%s", type(error).__name__)
        summary = await self._summary.summarize(invocation, action.final_snapshot, context=interaction)
        if summary is not None:
            source = CallSummarySource.GENERATED
        else:
            summary, source = fallback_call_summary(interaction.conversation.read_working().summary.text)
        result = CallEndingResult(
            summary=summary,
            summary_source=source,
            maintenance_succeeded=succeeded,
            maintenance_turn_seq=interaction.conversation.read_call_maintenance_progress(),
        )
        return d.ActionResult(
            action_id=action.action_id,
            status=d.ActionExecutionStatus.COMPLETED,
            error_code=None,
            # 维护失败也可能已经写入部分记忆，禁止把整个行动作为无副作用重试。
            irreversible_effect_committed=True,
            effect_ref=None,
            call_ending=result,
        )
