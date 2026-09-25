"""动态发布行动：把已决定的外部动态交给动态能力落库。"""

from __future__ import annotations

import src.domain.agent as d
from src.agent.processing.output_emitter import OutputEmitter
from src.agent.skills.expression.dynamic_publishing import DynamicPublishingSkill
from src.agent.skills.invocation import execution_invocation
from src.utils.logger import get_logger


class PublishDynamicHandler:
    """角色私有的动态发布处理器；只提交持久效果，不投递聊天输出。"""

    def __init__(self, character_id: str, publishing: DynamicPublishingSkill) -> None:
        self._character_id = character_id
        self._publishing = publishing
        self._logger = get_logger(__name__)

    async def realize(
        self, action: d.Action, execution_context: d.ExecutionContext, outputs: OutputEmitter
    ) -> d.ActionResult:
        """发布动态并报告已提交效果；失败返回稳定错误码且不声称已提交。"""
        _ = outputs
        if not isinstance(action, d.PublishDynamic):
            raise TypeError("PublishDynamicHandler 只处理 PublishDynamic")
        if execution_context.cancellation.is_cancelled:
            return self._failed(action, d.ExecutionErrorCode.CANCELLED)
        result = await self._publishing.publish(
            execution_invocation(self._character_id, execution_context, user_id=action.owner_user_id),
            action,
        )
        if result.ok and result.dynamic_id:
            return d.ActionResult(
                action_id=action.action_id,
                status=d.ActionExecutionStatus.COMPLETED,
                error_code=None,
                irreversible_effect_committed=True,
                effect_ref=d.EffectRef(kind=d.EffectKind.DYNAMIC_POST, effect_id=result.dynamic_id),
            )
        self._logger.error(
            "PUBLISH_DYNAMIC 失败 action_id=%s source=%s/%s",
            action.action_id,
            action.source.source_type,
            action.source.source_id,
        )
        return self._failed(
            action,
            (
                d.ExecutionErrorCode.CANCELLED
                if execution_context.cancellation.is_cancelled
                else d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE
            ),
        )

    @staticmethod
    def _failed(action: d.PublishDynamic, code: d.ExecutionErrorCode) -> d.ActionResult:
        status = (
            d.ActionExecutionStatus.CANCELLED
            if code is d.ExecutionErrorCode.CANCELLED
            else d.ActionExecutionStatus.FAILED
        )
        return d.ActionResult(
            action_id=action.action_id,
            status=status,
            error_code=code,
            irreversible_effect_committed=False,
            effect_ref=None,
        )
