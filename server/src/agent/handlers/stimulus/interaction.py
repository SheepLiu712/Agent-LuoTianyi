"""交互结束时释放 Agent 持有的上下文。"""
import src.domain.agent as d
from src.agent.context import ContextFactory
from src.agent.processing.plan_emitter import PlanEmitter


class InteractionEndingHandler:
    """处理交互结束通知，关闭现有上下文且不创建新的上下文。"""

    def __init__(self, contexts: ContextFactory) -> None:
        """绑定当前角色持有的上下文管理器 contexts。"""
        self._contexts = contexts

    async def handle(self, request: d.HandleStimulusRequest, plans: PlanEmitter) -> d.HandlingReport:
        """释放 request 对应的上下文并返回完成报告；本处理不产生 plans。"""
        await self._contexts.release(request.interaction.interaction_id)
        pending = tuple(item.stimulus_id for item in request.interaction.pending_stimuli)
        return d.HandlingReport(
            request_id=request.request_id, trigger_stimulus_id=request.stimulus.stimulus_id,
            basis_interaction_revision=request.interaction.interaction_revision,
            request_status=d.HandlingRequestStatus.COMPLETED,
            considered_pending_stimulus_ids=pending, consumed_pending_stimulus_ids=(),
            retained_pending_stimulus_ids=pending, emitted_plan_ids=(), reconsider_at=None,
            error_code=None, retryable=False,
        )
