"""触摸刺激的预制瞬时反应与独立表情恢复计划。"""

from typing import Protocol
from uuid import uuid4

import src.domain.agent as d
from src.agent.processing.plan_emitter import ActionPlanDraft, PlanEmitter
from src.agent.skills.expression.touch import TouchReaction
from src.utils.logger import get_logger


class TouchReactionSelector(Protocol):
    """选择一次可交付的触摸预制反应。"""

    def choose(self) -> TouchReaction | None:
        """返回反应；资源不可用或快速分支未命中时返回 None。"""
        ...


class TouchInteractionHandler:
    """把一次触摸转换为瞬时 SAY 及随后独立恢复计划。"""

    def __init__(self, reactions: TouchReactionSelector) -> None:
        """绑定角色触摸资源选择技能。"""
        self._reactions = reactions

    async def handle(
        self,
        request: d.HandleStimulusRequest,
        plans: PlanEmitter,
    ) -> d.HandlingReport:
        """成功时顺序交付两个计划，失败时记录并丢弃本次触摸。"""
        if not isinstance(request.stimulus, d.TouchInteraction):
            raise TypeError("TouchInteractionHandler 只处理 TouchInteraction")
        reaction = self._reactions.choose()
        if reaction is None:
            get_logger(__name__).error(
                "Touch reaction unavailable request_id=%s stimulus_id=%s",
                request.request_id,
                request.stimulus.stimulus_id,
            )
            return self._report(
                request,
                plans,
                status=d.HandlingRequestStatus.FAILED,
                error_code=d.HandlingErrorCode.DEPENDENCY_UNAVAILABLE,
            )
        source_ids = (request.stimulus.stimulus_id,)
        await plans.emit(ActionPlanDraft(
            source_stimulus_ids=source_ids,
            actions=(d.Say(
                action_id=str(uuid4()),
                content="",
                sound_content=None,
                prepared_audio_ref=reaction.audio_ref,
                tone=d.Tone(value="normal"),
                expression=d.ChangeExpression(expression_id=reaction.expression_id),
                delivery=d.OutputDelivery.EPHEMERAL_REACTION,
            ),),
        ))
        await plans.emit(ActionPlanDraft(
            source_stimulus_ids=source_ids,
            actions=(d.RestoreExpression(
                action_id=str(uuid4()),
                expression_id="normal",
                delivery=d.OutputDelivery.EPHEMERAL_REACTION,
            ),),
        ))
        return self._report(request, plans)

    @staticmethod
    def _report(
        request: d.HandleStimulusRequest,
        plans: PlanEmitter,
        *,
        status: d.HandlingRequestStatus = d.HandlingRequestStatus.COMPLETED,
        error_code: d.HandlingErrorCode | None = None,
    ) -> d.HandlingReport:
        pending = tuple(item.stimulus_id for item in request.interaction.pending_stimuli)
        return d.HandlingReport(
            request_id=request.request_id,
            trigger_stimulus_id=request.stimulus.stimulus_id,
            basis_interaction_revision=request.interaction.interaction_revision,
            request_status=status,
            considered_pending_stimulus_ids=pending,
            consumed_pending_stimulus_ids=(),
            retained_pending_stimulus_ids=pending,
            emitted_plan_ids=tuple(plans.accepted_ids),
            error_code=error_code,
            retryable=False,
        )
