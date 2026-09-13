"""交互结束通知的认知处理入口。"""
import src.domain.agent as d
from src.agent.processing.plan_emitter import PlanEmitter


class InteractionEndingHandler:
    """处理交互结束通知并返回结算；上下文由 Stage 释放。"""

    async def handle(self, request: d.HandleStimulusRequest, plans: PlanEmitter) -> d.HandlingReport:
        """确认 request 对应的交互结束，返回完成报告；本处理不产生 plans。"""
        pending = tuple(item.stimulus_id for item in request.interaction.pending_stimuli)
        return d.HandlingReport(
            request_id=request.request_id, trigger_stimulus_id=request.stimulus.stimulus_id,
            basis_interaction_revision=request.interaction.interaction_revision,
            request_status=d.HandlingRequestStatus.COMPLETED,
            considered_pending_stimulus_ids=pending, consumed_pending_stimulus_ids=(),
            retained_pending_stimulus_ids=pending, emitted_plan_ids=(),
            error_code=None, retryable=False,
        )
