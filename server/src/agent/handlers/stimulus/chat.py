"""聊天处理：单条文本预处理与落库，以及批次回复、反思入口。"""
from datetime import datetime
from uuid import uuid4

import src.domain.agent as d
from src.agent.context.models import ConversationEntry, TextContent
from src.agent.processing.plan_emitter import PlanEmitter
from src.agent.skills.cognitive import TextPreprocessingSkill
from src.utils.enum_type import ConversationSource


def _report(request: d.HandleStimulusRequest, *, consume: bool = False,
            prepared: d.PreprocessedInput | None = None) -> d.HandlingReport:
    ids = tuple(s.stimulus_id for s in request.interaction.pending_stimuli)
    return d.HandlingReport(request_id=request.request_id, trigger_stimulus_id=request.stimulus.stimulus_id,
        basis_interaction_revision=request.interaction.interaction_revision,
        request_status=d.HandlingRequestStatus.COMPLETED, considered_pending_stimulus_ids=ids,
        consumed_pending_stimulus_ids=ids if consume else (), retained_pending_stimulus_ids=() if consume else ids,
        emitted_plan_ids=(), retryable=False, error_code=None, preprocessed_input=prepared)


class ChatPreprocessingHandler:
    """单刺激预处理和落库；预处理完成不等于消费输入。"""

    def __init__(self, understanding: TextPreprocessingSkill) -> None:
        """注入文本语义预处理技能，用于提取歌曲实体等对话与检索线索。"""
        self._understanding = understanding

    async def handle(self, request: d.HandleStimulusRequest, plans: PlanEmitter) -> d.HandlingReport:
        """文本先理解并落库，再返回 READY 结果；不交付计划，不消费本批输入。"""
        stimulus = request.stimulus
        if isinstance(stimulus, d.TextMessage):
            terms = self._understanding.extract_terms(stimulus.text)
            entry = ConversationEntry(
                entry_id=str(uuid4()),
                timestamp=datetime.now(),
                source=ConversationSource.USER.value,
                content=TextContent(stimulus.text, terms),
            )
            await plans.context.conversation.append((entry,))
            prepared = d.PreprocessedInput(
                stimulus_id=stimulus.stimulus_id, text=stimulus.text,
                conversation_entry_ids=(entry.entry_id,),
            )
        elif isinstance(stimulus, (d.ImageMessage, d.VoiceMessage)):
            prepared = d.PreprocessedInput(stimulus_id=stimulus.stimulus_id, text=None)
        else:
            prepared = None
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
