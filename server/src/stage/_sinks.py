"""Stage 拥有的刺激、计划和输出接收实现。"""
from __future__ import annotations

from typing import TYPE_CHECKING
import src.domain.agent as d
from src.domain.stage import AgentPresentationChanged, AgentPresentationState

if TYPE_CHECKING:
    from .chat_stage import ChatStage


class StimulusInputSink:
    """将外部刺激放入所属 Stage，不等待 Agent 处理。"""

    def __init__(self, stage: ChatStage) -> None:
        """绑定负责校验、排队和处理刺激的 stage。"""
        self._stage = stage

    def can_accept(self, stimulus: d.Stimulus) -> bool:
        """检查 stimulus 的身份及当前容量；返回 True 只表示此刻可以入队。"""
        return self._stage._can_accept(stimulus)

    def submit(self, stimulus: d.Stimulus) -> bool:
        """同步接收 stimulus，返回是否入队；拒绝时不改变 Stage 状态。"""
        return self._stage._receive(stimulus)


class _PlanSink:
    def __init__(self, stage: ChatStage, request: d.HandleStimulusRequest) -> None:
        self.stage, self.request = stage, request
        self.ids: list[str] = []
        self.closed = False

    async def emit(self, plan: d.ActionPlan) -> d.PlanReceipt:
        """接收当前请求产生的 plan，返回计划接收结果；过时或越界则拒绝。"""
        request, stage = self.request, self.stage
        if self.closed or request.cancellation.is_cancelled:
            raise d.SinkRejectedError("request is stale", code=d.SinkRejectionCode.STALE_INTERACTION)
        if (plan.origin_request_id != request.request_id or plan.interaction_id != stage.interaction_id
                or plan.target_character_id != stage.character_id
                or plan.basis_interaction_revision != request.interaction.interaction_revision
                or plan.plan_id in self.ids or plan.plan_ordinal != len(self.ids)):
            raise d.SinkRejectedError("plan identity mismatch", code=d.SinkRejectionCode.IDENTITY_MISMATCH)
        if isinstance(plan.actions[0], d.StartThinking):
            stage._send(AgentPresentationChanged(interaction_id=stage.interaction_id,
                                                 state=AgentPresentationState.THINKING))
        else:
            stage._enqueue_plan(plan, request.cancellation)
        self.ids.append(plan.plan_id)
        return d.PlanReceipt(plan_id=plan.plan_id, status=d.PlanAcceptanceStatus.ACCEPTED)


class _AgentOutputSink:
    def __init__(self, stage: ChatStage) -> None:
        self.stage = stage
        self.active: tuple[str, str, d.OutputDelivery] | None = None

    async def emit(self, output: d.AgentOutput) -> d.OutputReceipt:
        """接收当前执行的 output 并交给 adapter；返回值表示已入队，不表示网络发送完成。"""
        context = self.stage._execution
        if context is None or output.interaction_id != self.stage.interaction_id or output.execution_id != context.execution_id:
            raise d.SinkRejectedError("output execution mismatch", code=d.SinkRejectionCode.IDENTITY_MISMATCH)
        identity = (output.execution_id, output.action_id, output.delivery)
        if self.active is not None and self.active != identity:
            raise d.SinkRejectedError("previous message has no end", code=d.SinkRejectionCode.CONTENT_CONFLICT)
        self.stage._send(output)
        self.active = None if isinstance(output, d.MessageEndOutput) else identity
        return d.OutputReceipt(execution_id=output.execution_id, sequence_no=output.sequence_no,
                               status=d.OutputAcceptanceStatus.ACCEPTED)
