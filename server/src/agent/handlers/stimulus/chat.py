"""聊天处理占位：验证编排契约，不调用模型、不写库、不生成用户输出。"""
import src.domain.agent as d
from src.agent.processing.plan_emitter import PlanEmitter


def _report(request: d.HandleStimulusRequest, *, consume: bool = False,
            prepared: d.PreprocessedInput | None = None) -> d.HandlingReport:
    ids = tuple(s.stimulus_id for s in request.interaction.pending_stimuli)
    return d.HandlingReport(request_id=request.request_id, trigger_stimulus_id=request.stimulus.stimulus_id,
        basis_interaction_revision=request.interaction.interaction_revision,
        request_status=d.HandlingRequestStatus.COMPLETED, considered_pending_stimulus_ids=ids,
        consumed_pending_stimulus_ids=ids if consume else (), retained_pending_stimulus_ids=() if consume else ids,
        emitted_plan_ids=(), retryable=False, error_code=None, preprocessed_input=prepared)


class ChatPreprocessingHandler:
    """单刺激预处理和落库的占位入口；当前只返回原始文本，不执行持久化。"""

    async def handle(self, request: d.HandleStimulusRequest, plans: PlanEmitter) -> d.HandlingReport:
        """返回 request 的预处理占位结果；真实处理可通过 plans.context 使用本交互上下文。"""
        stimulus = request.stimulus
        prepared = None
        if isinstance(stimulus, (d.TextMessage, d.ImageMessage, d.VoiceMessage)):
            prepared = d.PreprocessedInput(stimulus_id=stimulus.stimulus_id,
                text=stimulus.text if isinstance(stimulus, d.TextMessage) else None)
        return _report(request, prepared=prepared)


class ChatReplyHandler:
    """超时触发的批次回复占位；当前消费本批输入，不生成回复内容。"""

    async def handle(self, request: d.HandleStimulusRequest, plans: PlanEmitter) -> d.HandlingReport:
        """结算 request 的整批输入；注意力选择与回复生成逻辑尚未接入。"""
        return _report(request, consume=True)


class ChatReflectionHandler:
    """回复结算后的认知维护占位，不执行记忆或画像更新。"""

    async def handle(self, request: d.HandleStimulusRequest, plans: PlanEmitter) -> d.HandlingReport:
        """确认 request 的维护触发，不交付行动计划或修改 context。"""
        return _report(request)
