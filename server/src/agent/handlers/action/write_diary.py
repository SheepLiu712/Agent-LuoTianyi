"""WriteDiary 行动的私密动态发布实现。"""

from __future__ import annotations

import src.domain.agent as d
from src.agent.processing.output_emitter import OutputEmitter
from src.agent.skills.expression.diary_writing import DiaryWritingSkill
from src.utils.logger import get_logger


class WriteDiaryHandler:
    def __init__(self, writing: DiaryWritingSkill) -> None:
        self._writing = writing
        self._logger = get_logger(__name__)

    async def realize(
        self, action: d.Action, execution_context: d.ExecutionContext, outputs: OutputEmitter,
    ) -> d.ActionResult:
        _ = outputs
        if not isinstance(action, d.WriteDiary):
            raise TypeError("WriteDiaryHandler 只处理 WriteDiary")
        if execution_context.cancellation.is_cancelled:
            return self._failed(action, d.ExecutionErrorCode.CANCELLED)
        result = self._writing.publish(action)
        if result.ok and result.dynamic_id:
            return d.ActionResult(
                action_id=action.action_id,
                status=d.ActionExecutionStatus.COMPLETED,
                error_code=None,
                irreversible_effect_committed=True,
                effect_ref=d.EffectRef(
                    kind=d.EffectKind.DYNAMIC_POST, effect_id=result.dynamic_id,
                ),
            )
        self._logger.error("WRITE_DIARY 失败 action_id=%s user=%s date=%s",
                           action.action_id, action.owner_user_id, action.local_date)
        return self._failed(action, d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE)

    @staticmethod
    def _failed(action: d.WriteDiary, code: d.ExecutionErrorCode) -> d.ActionResult:
        status = (d.ActionExecutionStatus.CANCELLED if code is d.ExecutionErrorCode.CANCELLED
                  else d.ActionExecutionStatus.FAILED)
        return d.ActionResult(
            action_id=action.action_id, status=status, error_code=code,
            irreversible_effect_committed=False, effect_ref=None,
        )
