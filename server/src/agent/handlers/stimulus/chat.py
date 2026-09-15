"""聊天处理：单条文本预处理与落库，以及批次回复、反思入口。"""
from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

import src.domain.agent as d
from src.agent.context.models import ConversationEntry, SongContent, TextContent
from src.agent.processing.plan_emitter import ActionPlanDraft, PlanEmitter
from src.agent.skills.cognitive import ResponseCompositionSkill, TextPreprocessingSkill
from src.agent.skills.conversation.compaction import ConversationCompactionSkill
from src.agent.skills.reflection import ReflectionSkill
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
                timestamp=datetime.now(timezone.utc).astimezone().replace(tzinfo=None),
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


def _recent_sung_segments(snapshot) -> set[tuple[str, str]]:
    """从近期对话中取出已演唱的歌曲片段，用于本次演唱排除。"""
    sung: set[tuple[str, str]] = set()
    for entry in snapshot.entries:
        content = entry.content
        if isinstance(content, SongContent) and content.segment:
            sung.add((content.song, content.segment))
    return sung


def _render_history(snapshot) -> str:
    """把已压缩总结与近期对话渲染成生成提示使用的历史文本。"""
    lines = []
    if snapshot.summary.text:
        lines.append(snapshot.summary.text)
    lines.extend(f"{entry.source}: {entry.content.text}" for entry in snapshot.entries)
    return "\n".join(lines)


def _reply_actions(request: d.HandleStimulusRequest, drafts) -> tuple[d.Action, ...]:
    """把回复草稿按序转成 Say/Sing 行动；空白且演唱的草稿被丢弃。"""
    actions: list[d.Action] = []
    for index, draft in enumerate(drafts):
        action_id = f"{request.request_id}-r{index}"
        expression = d.ChangeExpression(expression_id=draft.expression) if draft.expression else None
        if draft.sing is not None:
            actions.append(d.Sing(action_id=action_id, song_id=draft.sing[0],
                                  segment_id=draft.sing[1], expression=expression))
        elif draft.content.strip():
            actions.append(d.Say(action_id=action_id, content=draft.content,
                                 sound_content=draft.sound_content or None, prepared_audio_ref=None,
                                 tone=d.Tone(value=draft.tone or "normal"), expression=expression,
                                 delivery=d.OutputDelivery.CONVERSATION))
    return tuple(actions)


def _reply_entries(drafts) -> tuple[ConversationEntry, ...]:
    """把回复草稿转成 agent 侧正式对话记录。"""
    entries: list[ConversationEntry] = []
    for draft in drafts:
        if draft.sing is not None:
            song, segment = draft.sing
            text = f"{draft.content}\n{draft.lyrics}".strip() if draft.lyrics else draft.content
            entries.append(ConversationEntry(
                entry_id=str(uuid4()),
                timestamp=datetime.now(timezone.utc).astimezone().replace(tzinfo=None),
                source=ConversationSource.AGENT.value,
                content=SongContent(text, song, segment)))
        elif draft.content.strip():
            entries.append(ConversationEntry(
                entry_id=str(uuid4()),
                timestamp=datetime.now(timezone.utc).astimezone().replace(tzinfo=None),
                source=ConversationSource.AGENT.value, content=TextContent(draft.content)))
    return tuple(entries)


class ChatReplyHandler:
    """到期批次回复：生成回复、落库并交付有序 Say/Sing 计划。"""

    def __init__(self, composition: ResponseCompositionSkill,
                 understanding: TextPreprocessingSkill) -> None:
        """注入回复生成技能与文本预处理技能（用于演唱尝试线索）。"""
        self._composition = composition
        self._understanding = understanding

    async def handle(self, request: d.HandleStimulusRequest, plans: PlanEmitter) -> d.HandlingReport:
        """按接收顺序把整批输入作为一次回复：召回→生成→落库→交付计划，并按 ID 消费。"""
        pending = tuple(s.stimulus_id for s in request.interaction.pending_stimuli)
        reply_topic = "\n".join(
            item.text.strip() for item in request.prepared_inputs if item.text and item.text.strip())
        drafts: tuple = ()
        if reply_topic:
            await plans.emit(ActionPlanDraft(
                source_stimulus_ids=pending,
                actions=(d.StartThinking(action_id=f"{request.request_id}-thinking"),)))
            identity = plans.context.identity
            snapshot = plans.context.conversation.read()
            plans.set_interruptible(True)
            drafts = await self._composition.compose(
                character_id=identity.character_id, user_id=identity.user_id,
                reply_topic=reply_topic, conversation_history=_render_history(snapshot),
                memory_queries=(reply_topic,),
                sing_attempts=self._understanding.extract_terms(reply_topic),
                excluded_segments=_recent_sung_segments(snapshot))
            plans.set_interruptible(False)
        actions = _reply_actions(request, drafts)
        if actions:
            entries = _reply_entries(drafts)
            if entries:
                await plans.context.conversation.append(entries)
            await plans.emit(ActionPlanDraft(source_stimulus_ids=pending, actions=actions))
        return replace(_report(request, consume=True), emitted_plan_ids=tuple(plans.accepted_ids))


def _reflection_dialogue(request: d.HandleStimulusRequest, snapshot) -> str:
    """把本次已消费的用户输入与近期 agent 回复拼成记忆提炼依据。"""
    lines = [f"user: {item.text}" for item in request.prepared_inputs
             if item.text and item.text.strip()]
    lines.extend(f"agent: {entry.content.text}" for entry in snapshot.entries
                 if entry.source == ConversationSource.AGENT.value)
    return "\n".join(lines)


class ChatReflectionHandler:
    """回复结算后的认知维护：记忆沉淀、上下文压缩与用户画像更新。"""

    def __init__(self, reflection: ReflectionSkill, compaction: ConversationCompactionSkill) -> None:
        """注入反思技能与共享压缩技能；不产生用户可见输出。"""
        self._reflection = reflection
        self._compaction = compaction

    async def handle(self, request: d.HandleStimulusRequest, plans: PlanEmitter) -> d.HandlingReport:
        """依次沉淀记忆、按阈值压缩上下文、更新画像；不交付计划也不消费输入。"""
        context = plans.context
        identity = context.identity
        if identity.user_id is None:
            return _report(request)
        snapshot = context.conversation.read()
        dialogue = _reflection_dialogue(request, snapshot)
        if dialogue:
            await self._reflection.consolidate_memories(
                character_id=identity.character_id, user_id=identity.user_id,
                current_dialogue=dialogue, conversation_history=_render_history(snapshot))
        compaction = await self._compaction.compact(context.conversation)
        if compaction is not None:
            await context.conversation.compact(compaction)
        if snapshot.summary.text or snapshot.entries:
            await self._reflection.update_profile(
                character_id=identity.character_id, user_id=identity.user_id,
                summary=snapshot.summary.text,
                recent_conversation=[f"{entry.source}: {entry.content.text}" for entry in snapshot.entries])
        return _report(request)
