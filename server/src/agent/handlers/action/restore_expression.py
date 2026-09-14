"""独立表情恢复行动的输出实现。"""

import src.domain.agent as d
from src.agent.processing.output_drafts import ExpressionDraft
from src.agent.processing.output_emitter import OutputEmitter


class RestoreExpressionHandler:
    """把独立恢复行动实现为唯一一份表情输出。"""

    async def realize(
        self,
        action: d.Action,
        execution_context: d.ExecutionContext,
        outputs: OutputEmitter,
    ) -> d.ActionResult:
        """交付目标表情并返回无不可逆效果的完成结果。"""
        if not isinstance(action, d.RestoreExpression):
            raise TypeError("RestoreExpressionHandler 只处理 RestoreExpression")
        if execution_context.cancellation.is_cancelled:
            return d.ActionResult(
                action_id=action.action_id,
                status=d.ActionExecutionStatus.CANCELLED,
                error_code=d.ExecutionErrorCode.CANCELLED,
                irreversible_effect_committed=False,
                effect_ref=None,
            )
        await outputs.emit(ExpressionDraft(
            expression=d.ChangeExpression(expression_id=action.expression_id),
            delivery=action.delivery,
        ))
        return d.ActionResult(
            action_id=action.action_id,
            status=d.ActionExecutionStatus.COMPLETED,
            error_code=None,
            irreversible_effect_committed=False,
            effect_ref=None,
        )
