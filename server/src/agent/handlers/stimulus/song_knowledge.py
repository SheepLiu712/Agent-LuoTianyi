"""歌曲知识候选的受控处理入口：只做接纳，不产生外部效果。"""

from __future__ import annotations

import src.domain.agent as d
from src.agent.processing.plan_emitter import PlanEmitter
from src.agent.skills.knowledge.song_acceptance import (
    SongAcceptanceStatus,
    SongKnowledgeAcceptanceSkill,
)
from src.utils.logger import get_logger


class SongKnowledgeHandler:
    """把已规范化的歌曲候选交给接纳技能，并按真实结果结算当前刺激。

    接纳属于 Agent 内部状态变更，不进 ActionPlan；本处理器不交付任何计划，
    因此世界链路不会因它产生实时输出。
    """

    def __init__(self, skill: SongKnowledgeAcceptanceSkill) -> None:
        self._skill = skill
        self._logger = get_logger(__name__)

    async def handle(
        self, request: d.HandleStimulusRequest, plans: PlanEmitter,
    ) -> d.HandlingReport:
        """接纳候选：成功或已有项跳过时消费该刺激，失败与候选不完整时明确报告。"""
        _ = plans
        stimulus = request.stimulus
        if not isinstance(stimulus, d.SongKnowledgeDiscovered):
            raise TypeError("SongKnowledgeHandler 只处理歌曲知识候选")
        pending = tuple(item.stimulus_id for item in request.interaction.pending_stimuli)
        result = await self._skill.accept(
            source_ref=stimulus.source_ref,
            external_song_id=stimulus.external_song_id,
            revision=stimulus.revision,
            candidate=stimulus.candidate,
        )
        if result.status is SongAcceptanceStatus.ACCEPTED:
            self._logger.info("歌曲知识已接纳：%s", result.detail)
            return self._report(request, pending, d.HandlingRequestStatus.COMPLETED, None,
                                consumed=(stimulus.stimulus_id,))
        if result.status is SongAcceptanceStatus.ALREADY_PRESENT:
            self._logger.info("歌曲知识已有项，跳过：%s", result.detail)
            return self._report(request, pending, d.HandlingRequestStatus.COMPLETED, None,
                                consumed=(stimulus.stimulus_id,))
        self._logger.error("歌曲知识接纳失败：%s", result.detail)
        return self._report(request, pending, d.HandlingRequestStatus.FAILED,
                            d.HandlingErrorCode.DEPENDENCY_UNAVAILABLE, consumed=())

    @staticmethod
    def _report(
        request: d.HandleStimulusRequest, pending: tuple[str, ...],
        status: d.HandlingRequestStatus, error_code: d.HandlingErrorCode | None,
        *, consumed: tuple[str, ...],
    ) -> d.HandlingReport:
        return d.HandlingReport(
            request_id=request.request_id,
            trigger_stimulus_id=request.stimulus.stimulus_id,
            basis_interaction_revision=request.interaction.interaction_revision,
            request_status=status,
            considered_pending_stimulus_ids=pending,
            consumed_pending_stimulus_ids=consumed,
            retained_pending_stimulus_ids=tuple(item for item in pending if item not in consumed),
            emitted_plan_ids=(),
            error_code=error_code,
            retryable=False,
        )


__all__ = ["SongKnowledgeHandler"]
