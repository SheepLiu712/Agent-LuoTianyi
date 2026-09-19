"""世界与活动事实的受控处理入口。"""

from collections.abc import Mapping
from typing import Final, Protocol

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


class WorldObservationBranch(Protocol):
    """按 `observation_kind` 处理一类世界观察。"""

    async def handle(self, request: d.HandleStimulusRequest, plans: PlanEmitter) -> d.HandlingReport:
        """处理本次观察并交付计划或明确结算。"""
        ...


class WorldActivityHandler:
    """消费已规范化的世界或活动事实，不取得 world owner 或存储对象。

    未登记分支的观察类别仍按事实 ID 结算（占位行为），已登记分支承担真实认知。
    """

    def __init__(self, branches: Mapping[str, WorldObservationBranch] | None = None) -> None:
        """按 `observation_kind.value` 登记世界观察分支。"""
        self._branches = dict(branches or {})

    async def handle(
        self,
        request: d.HandleStimulusRequest,
        plans: PlanEmitter,
    ) -> d.HandlingReport:
        """按观察类别分派；无分支时结算当前刺激，不产生计划。"""
        stimulus = request.stimulus
        if isinstance(stimulus, d.WorldObservation):
            branch = self._branches.get(stimulus.observation_kind.value)
            if branch is not None:
                return await branch.handle(request, plans)
        _ = plans
        pending = tuple(item.stimulus_id for item in request.interaction.pending_stimuli)
        consumed = (request.stimulus.stimulus_id,)
        return d.HandlingReport(
            request_id=request.request_id,
            trigger_stimulus_id=request.stimulus.stimulus_id,
            basis_interaction_revision=request.interaction.interaction_revision,
            request_status=d.HandlingRequestStatus.COMPLETED,
            considered_pending_stimulus_ids=pending,
            consumed_pending_stimulus_ids=consumed,
            retained_pending_stimulus_ids=tuple(item for item in pending if item not in consumed),
            emitted_plan_ids=(),
            error_code=None,
            retryable=False,
        )
