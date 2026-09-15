"""世界与活动事实的受控处理入口。"""
from typing import Final

import src.domain.agent as d
from src.agent.processing.plan_emitter import PlanEmitter

WORLD_ACTIVITY_STIMULUS_KINDS: Final = (
    d.StimulusKind.WORLD_OBSERVATION,
    d.StimulusKind.ACTIVITY_OBSERVATION,
    d.StimulusKind.DYNAMIC_OBSERVED,
    d.StimulusKind.DIARY_PLANNING_DUE,
    d.StimulusKind.SONG_KNOWLEDGE_DISCOVERED,
    d.StimulusKind.SONG_LEARNED,
)


class WorldActivityHandler:
    """消费已规范化的世界或活动事实，不取得 world owner 或存储对象。"""

    async def handle(
        self, request: d.HandleStimulusRequest, plans: PlanEmitter,
    ) -> d.HandlingReport:
        """按事实 ID 结算当前刺激；后续认知只可从 request 与 plans.context 扩展。"""
        _ = plans
        pending = tuple(item.stimulus_id for item in request.interaction.pending_stimuli)
        consumed = (request.stimulus.stimulus_id,)
        return d.HandlingReport(
            request_id=request.request_id, trigger_stimulus_id=request.stimulus.stimulus_id,
            basis_interaction_revision=request.interaction.interaction_revision,
            request_status=d.HandlingRequestStatus.COMPLETED,
            considered_pending_stimulus_ids=pending, consumed_pending_stimulus_ids=consumed,
            retained_pending_stimulus_ids=tuple(item for item in pending if item not in consumed),
            emitted_plan_ids=(), error_code=None, retryable=False,
        )
