"""citywalk 完成事实的角色表达与动态发布决定。

`observation_kind` 取值是 world 生产者与 Agent 消费者之间的稳定约定，
记录在 `接口文档/world/README.md` 的「世界事实投递」一节。
"""

from __future__ import annotations

from uuid import uuid4

import src.domain.agent as d
from src.agent.processing.plan_emitter import ActionPlanDraft, PlanEmitter
from src.agent.skills.expression.dynamic_publishing import DynamicPublishingSkill
from src.agent.skills.invocation import handling_invocation
from src.utils.logger import get_logger

CITYWALK_OBSERVATION_KIND = "citywalk_completed"
CITYWALK_SOURCE_TYPE = "citywalk"
CITYWALK_INSTRUCTION = (
    "这是一次城市漫步完成后的角色动态。请以角色的第一人称视角分享散步中的见闻和感受，"
    "语气轻松自然，带一点生活气息；不要写成后台报告，不要逐条罗列字段。"
)


class CitywalkObservationHandler:
    """把散步摘要表达为角色动态，并交付一个 PublishDynamic 计划。"""

    def __init__(self, publishing: DynamicPublishingSkill) -> None:
        self._publishing = publishing
        self._logger = get_logger(__name__)

    async def handle(self, request: d.HandleStimulusRequest, plans: PlanEmitter) -> d.HandlingReport:
        """生成角色化正文并交付发布计划；生成失败时明确失败且不交付计划。"""
        stimulus = request.stimulus
        if not isinstance(stimulus, d.WorldObservation):
            raise TypeError("CitywalkObservationHandler 只处理 WorldObservation")
        body = await self._publishing.compose(
            handling_invocation(request, plans.context),
            dynamic_type=CITYWALK_SOURCE_TYPE,
            instruction=CITYWALK_INSTRUCTION,
            structured_context=stimulus.fact.summary,
        )
        if not body.strip():
            self._logger.error("citywalk 动态正文生成为空，未交付计划 fact=%s", stimulus.fact.fact_id)
            return self._report(request, d.HandlingRequestStatus.FAILED, d.HandlingErrorCode.DEPENDENCY_UNAVAILABLE, ())
        action = d.PublishDynamic(
            action_id=str(uuid4()),
            body=body,
            media_refs=(),
            visibility=d.Visibility.GLOBAL,
            owner_user_id=None,
            source=d.DynamicSource(source_type=CITYWALK_SOURCE_TYPE, source_id=stimulus.fact.fact_id),
            allow_comment=True,
        )
        receipt = await plans.emit(
            ActionPlanDraft(
                source_stimulus_ids=(stimulus.stimulus_id,),
                actions=(action,),
            )
        )
        return self._report(
            request, d.HandlingRequestStatus.COMPLETED, None, (stimulus.stimulus_id,), plans=(receipt.plan_id,)
        )

    @staticmethod
    def _report(
        request: d.HandleStimulusRequest,
        status: d.HandlingRequestStatus,
        error_code: d.HandlingErrorCode | None,
        consumed: tuple[str, ...],
        *,
        plans: tuple[str, ...] = (),
    ) -> d.HandlingReport:
        pending = tuple(item.stimulus_id for item in request.interaction.pending_stimuli)
        return d.HandlingReport(
            request_id=request.request_id,
            trigger_stimulus_id=request.stimulus.stimulus_id,
            basis_interaction_revision=request.interaction.interaction_revision,
            request_status=status,
            considered_pending_stimulus_ids=pending,
            consumed_pending_stimulus_ids=consumed,
            retained_pending_stimulus_ids=tuple(item for item in pending if item not in consumed),
            emitted_plan_ids=plans,
            error_code=error_code,
            retryable=False,
        )
