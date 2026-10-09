"""COGNITIVE_MAINTENANCE 行动：通过 Agent 技能维护长期认知。"""

from __future__ import annotations

import src.domain.agent as d
from src.agent.processing.output_emitter import OutputEmitter
from src.agent.skills.cognitive_maintenance import CognitiveMaintenanceSkill
from src.agent.skills.invocation import execution_invocation


class CognitiveMaintenanceActionHandler:
    """执行统一认知维护；不产生用户可见输出。"""

    def __init__(self, character_id: str, skill: CognitiveMaintenanceSkill) -> None:
        self._character_id = character_id
        self._skill = skill

    async def realize(
        self,
        action: d.Action,
        execution_context: d.ExecutionContext,
        outputs: OutputEmitter,
    ) -> d.ActionResult:
        _ = outputs
        if not isinstance(action, d.CognitiveMaintenance):
            raise TypeError("CognitiveMaintenanceActionHandler 只处理 CognitiveMaintenance")
        context = execution_context.interaction_context
        if context is None or not all(hasattr(context, name) for name in ("identity", "conversation", "user")):
            return self._result(action, d.ActionExecutionStatus.FAILED, d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE)
        try:
            if context.identity.user_id is None:
                return self._result(action)
            invocation = execution_invocation(
                self._character_id,
                execution_context,
                user_id=context.identity.user_id,
            )
            if action.reason is d.MaintenanceReason.COMPACTION_THRESHOLD:
                await self._skill.maintain_if_compaction_needed(invocation, context)
            else:
                await self._skill.maintain(invocation, context, reason=action.reason)
            return self._result(action)
        finally:
            # 旧 Reflection 的每轮召回清理语义保留在行动结束边界。
            if context is not None and hasattr(context, "recalled_memory"):
                context.recalled_memory.clear()

    @staticmethod
    def _result(
        action: d.CognitiveMaintenance,
        status: d.ActionExecutionStatus = d.ActionExecutionStatus.COMPLETED,
        error: d.ExecutionErrorCode | None = None,
    ) -> d.ActionResult:
        return d.ActionResult(
            action_id=action.action_id,
            status=status,
            error_code=error,
            irreversible_effect_committed=False,
            effect_ref=None,
        )
