"""动态回复行动：把已决定的评论回复交给动态能力落库。"""

from __future__ import annotations

import src.domain.agent as d
from src.agent.processing.output_emitter import OutputEmitter
from src.agent.skills.expression.dynamic_reply import DynamicReplySkill
from src.utils.logger import get_logger


class ReplyDynamicHandler:
    """角色私有的动态回复处理器；只提交持久效果，不投递聊天输出。"""

    def __init__(self, character_id: str, reply: DynamicReplySkill) -> None:
        self._character_id = character_id
        self._reply = reply
        self._logger = get_logger(__name__)

    async def realize(
        self, action: d.Action, execution_context: d.ExecutionContext, outputs: OutputEmitter,
    ) -> d.ActionResult:
        """发布评论并报告已提交效果；失败返回稳定错误码且不声称已提交。"""
        _ = outputs
        if not isinstance(action, d.ReplyDynamic):
            raise TypeError("ReplyDynamicHandler 只处理 ReplyDynamic")
        if execution_context.cancellation.is_cancelled:
            return self._failed(action, d.ExecutionErrorCode.CANCELLED)
        result = self._reply.publish(action)
        if result.ok and result.comment_id:
            return d.ActionResult(
                action_id=action.action_id, status=d.ActionExecutionStatus.COMPLETED,
                error_code=None, irreversible_effect_committed=True,
                effect_ref=d.EffectRef(kind=d.EffectKind.DYNAMIC_COMMENT,
                                       effect_id=result.comment_id),
            )
        self._logger.error(
            "REPLY_DYNAMIC 失败 action_id=%s dynamic=%s parent=%s",
            action.action_id, action.target.dynamic_id, action.target.parent_comment_id,
        )
        return self._failed(
            action,
            d.ExecutionErrorCode.CANCELLED if execution_context.cancellation.is_cancelled
            else d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE,
        )

    @staticmethod
    def _failed(action: d.ReplyDynamic, code: d.ExecutionErrorCode) -> d.ActionResult:
        status = (d.ActionExecutionStatus.CANCELLED if code is d.ExecutionErrorCode.CANCELLED
                  else d.ActionExecutionStatus.FAILED)
        return d.ActionResult(action_id=action.action_id, status=status, error_code=code,
                              irreversible_effect_committed=False, effect_ref=None)
