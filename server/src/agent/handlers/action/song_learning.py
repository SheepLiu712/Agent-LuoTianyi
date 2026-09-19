"""学歌派发行动：把已决定的学歌请求交给持久任务。"""

from __future__ import annotations

import src.domain.agent as d
from src.agent.processing.output_emitter import OutputEmitter
from src.agent.skills.expression.song_learning import SongLearningDispatchSkill
from src.utils.logger import get_logger


class RequestSongLearningHandler:
    """角色私有的学歌派发处理器；不在一次 realize 内等待完整学习。"""

    def __init__(self, character_id: str, dispatch: SongLearningDispatchSkill) -> None:
        self._character_id = character_id
        self._dispatch = dispatch
        self._logger = get_logger(__name__)

    async def realize(
        self, action: d.Action, execution_context: d.ExecutionContext, outputs: OutputEmitter
    ) -> d.ActionResult:
        """派发学歌请求并报告已提交任务身份；重复请求标记为已完成。"""
        _ = outputs
        if not isinstance(action, d.RequestSongLearning):
            raise TypeError("RequestSongLearningHandler 只处理 RequestSongLearning")
        if execution_context.cancellation.is_cancelled:
            return self._failed(action, d.ExecutionErrorCode.CANCELLED)
        try:
            requested = self._dispatch.request(song_id=action.song_id)
        except Exception:
            self._logger.exception("学歌派发失败 song=%s", action.song_id)
            return self._failed(action, d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE)
        if not requested:
            self._logger.info("学歌请求已在愿望清单中 song=%s dedup=%s", action.song_id, action.dedup_key)
        return d.ActionResult(
            action_id=action.action_id,
            status=(d.ActionExecutionStatus.COMPLETED if requested else d.ActionExecutionStatus.ALREADY_COMPLETED),
            error_code=None,
            irreversible_effect_committed=True,
            effect_ref=d.EffectRef(kind=d.EffectKind.SONG_LEARNING_JOB, effect_id=action.song_id),
        )

    @staticmethod
    def _failed(action: d.RequestSongLearning, code: d.ExecutionErrorCode) -> d.ActionResult:
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
