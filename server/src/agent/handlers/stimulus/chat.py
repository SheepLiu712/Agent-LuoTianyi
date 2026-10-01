"""聊天处理：单条文本预处理与落库，以及批次回复、反思入口。"""

from dataclasses import replace
from datetime import timedelta
from typing import Final
from uuid import uuid4

from typing_extensions import assert_never

import src.domain.agent as d
from src.agent.context.models import (
    AudioContent,
    ConversationEntry,
    ImageContent,
    RecallEntry,
    SongContent,
    TextContent,
)
from src.agent.processing.plan_emitter import ActionPlanDraft, PlanEmitter
from src.agent.processing.reply_delivery import build_reply_delivery, render_conversation_history
from src.agent.skills.cognitive import (
    AudioUnderstandingSkill,
    ExplicitMemoryIntentSkill,
    ImageUnderstandingSkill,
    ResponseCompositionSkill,
    TextPreprocessingSkill,
)
from src.agent.skills.invocation import handling_invocation
from src.agent.skills.mutation import IntentionalMemoryCommit
from src.utils.enum_type import ConversationSource

_MEMORY_ACK_REPLY_TOPIC_PREFIX: Final = "刚刚已经把这条用户长期记忆提交完成，请用角色口吻简短确认"


def _report(
    request: d.HandleStimulusRequest, *, consume: bool = False, prepared: d.PreprocessedInput | None = None
) -> d.HandlingReport:
    ids = tuple(s.stimulus_id for s in request.interaction.pending_stimuli)
    return d.HandlingReport(
        request_id=request.request_id,
        trigger_stimulus_id=request.stimulus.stimulus_id,
        basis_interaction_revision=request.interaction.interaction_revision,
        request_status=d.HandlingRequestStatus.COMPLETED,
        considered_pending_stimulus_ids=ids,
        consumed_pending_stimulus_ids=ids if consume else (),
        retained_pending_stimulus_ids=() if consume else ids,
        emitted_plan_ids=(),
        retryable=False,
        error_code=None,
        preprocessed_input=prepared,
    )


class ChatPreprocessingHandler:
    """单刺激预处理和落库；预处理完成不等于消费输入。"""

    def __init__(
        self,
        text_understanding: TextPreprocessingSkill,
        image_understanding: ImageUnderstandingSkill | None = None,
        audio_understanding: AudioUnderstandingSkill | None = None,
    ) -> None:
        """注入文本线索提取与可选的受控图片理解技能。"""
        self._text_understanding = text_understanding
        self._image_understanding = image_understanding
        self._audio_understanding = audio_understanding

    async def handle(self, request: d.HandleStimulusRequest, plans: PlanEmitter) -> d.HandlingReport:
        """文本先理解并落库，再返回 READY 结果；不交付计划，不消费本批输入。"""
        stimulus = request.stimulus
        # Conversation timestamps are stored as naive server-local time. Agent replies
        # use the same convention, so convert the UTC interaction clock first.
        fact_time = request.interaction.now.astimezone().replace(tzinfo=None) + timedelta(
            microseconds=request.interaction.interaction_revision * 10
        )
        match stimulus:
            case d.TextMessage():
                terms = self._text_understanding.extract_terms(stimulus.text)
                entry = ConversationEntry(
                    entry_id=str(uuid4()),
                    timestamp=fact_time,
                    source=ConversationSource.USER.value,
                    content=TextContent(stimulus.text, terms),
                )
                await plans.context.conversation.append((entry,))
                prepared = d.PreprocessedInput(
                    stimulus_id=stimulus.stimulus_id,
                    text=stimulus.text,
                    conversation_entry_ids=(entry.entry_id,),
                )
            case d.ImageMessage():
                if self._image_understanding is None:
                    raise RuntimeError("Image understanding skill is not configured")
                owner_user_id = request.interaction.user_id
                if owner_user_id is None:
                    raise RuntimeError("Image stimulus requires an authenticated user")
                media, description = await self._image_understanding.understand(
                    stimulus.media_ref,
                    owner_user_id=owner_user_id,
                )
                machine_text = f"[图片理解]: {description}"
                terms = self._text_understanding.extract_terms(machine_text)
                media_entry = ConversationEntry(
                    entry_id=str(uuid4()),
                    timestamp=fact_time,
                    source=ConversationSource.USER.value,
                    content=ImageContent(
                        text=machine_text,
                        mime_type=media.mime_type,
                        terms=terms,
                        media_id=stimulus.media_ref.media_id,
                    ),
                )
                await plans.context.conversation.append((media_entry,))
                prepared = d.PreprocessedInput(
                    stimulus_id=stimulus.stimulus_id,
                    text=machine_text,
                    conversation_entry_ids=(media_entry.entry_id,),
                )
            case d.VoiceMessage():
                if self._audio_understanding is None:
                    raise RuntimeError("Audio understanding skill is not configured")
                if stimulus.media_ref is None:
                    raise RuntimeError("Voice stimulus requires persisted audio media")
                owner_user_id = request.interaction.user_id
                if owner_user_id is None:
                    raise RuntimeError("Voice stimulus requires an authenticated user")
                media, status, result = await self._audio_understanding.understand(
                    stimulus.media_ref,
                    owner_user_id=owner_user_id,
                )
                audio = AudioContent(
                    media_id=stimulus.media_ref.media_id,
                    mime_type=media.mime_type,
                    duration_ms=stimulus.duration_ms,
                    understanding_status=status,
                    transcript=result.transcript,
                    emotion=result.emotion,
                    sound_description=result.sound_description,
                )
                entry = ConversationEntry(
                    entry_id=stimulus.message_uuid,
                    timestamp=fact_time,
                    source=ConversationSource.USER.value,
                    content=audio,
                )
                await plans.context.conversation.append((entry,))
                prepared = d.PreprocessedInput(
                    stimulus_id=stimulus.stimulus_id,
                    text=audio.text,
                    conversation_entry_ids=(entry.entry_id,),
                )
            case d.UserTyping() | d.ImageSelectionOpened() | d.ImageSelectionClosed() | d.TouchInteraction():
                prepared = None
            case unreachable:
                assert_never(unreachable)
        return _report(request, prepared=prepared)


def _recent_sung_segments(snapshot) -> set[tuple[str, str]]:
    """从近期对话中取出已演唱的歌曲片段，用于本次演唱排除。"""
    sung: set[tuple[str, str]] = set()
    for entry in snapshot.entries:
        content = entry.content
        if isinstance(content, SongContent) and content.segment:
            sung.add((content.song, content.segment))
    return sung


def _attach_recall(plans: PlanEmitter, request: d.HandleStimulusRequest, hits) -> None:
    """把本次召回命中挂到触发刺激上；重复标识直接跳过，不影响回复交付。"""
    stimulus_id = request.stimulus.stimulus_id
    entries = tuple(
        RecallEntry(entry_id=f"{request.request_id}-recall{index}", stimulus_id=stimulus_id, content=hit)
        for index, hit in enumerate(hits)
    )
    if entries:
        plans.context.recalled_memory.append(entries)


def _may_emit_formal(request: d.HandleStimulusRequest, basis: int) -> bool:
    """正式计划只在未取消且依据修订未变时交付。"""
    return not request.cancellation.is_cancelled and request.interaction.interaction_revision == basis


def _failed_memory_report(request: d.HandleStimulusRequest) -> d.HandlingReport:
    return replace(
        _report(request),
        request_status=d.HandlingRequestStatus.FAILED,
        error_code=d.HandlingErrorCode.INTERNAL_ERROR,
    )


class ChatReplyHandler:
    """到期批次回复：生成回复、落库并交付有序 Say/Sing 计划。"""

    def __init__(
        self,
        composition: ResponseCompositionSkill,
        understanding: TextPreprocessingSkill,
        memory_intent: ExplicitMemoryIntentSkill | None = None,
        memory_commit: IntentionalMemoryCommit | None = None,
    ) -> None:
        """注入回复生成、文本预处理以及可选的明确记忆识别与提交技能。"""
        self._composition = composition
        self._understanding = understanding
        self._memory_intent = memory_intent
        self._memory_commit = memory_commit

    async def handle(self, request: d.HandleStimulusRequest, plans: PlanEmitter) -> d.HandlingReport:
        """按接收顺序把整批输入作为一次回复：召回→生成→落库→交付计划，并按 ID 消费。"""
        pending = tuple(s.stimulus_id for s in request.interaction.pending_stimuli)
        memory_items, reply_parts = self._partition_inputs(request.prepared_inputs)
        if memory_items:
            report = await self._handle_memory_acknowledgement(
                request,
                plans,
                pending,
                memory_items,
                reply_parts,
            )
        else:
            report = await self._handle_conversation_reply(request, plans, pending, reply_parts)
        if report.request_status is d.HandlingRequestStatus.COMPLETED:
            await self._emit_reflection(plans, request, pending)
            report = replace(report, emitted_plan_ids=tuple(plans.accepted_ids))
        return report

    @staticmethod
    async def _emit_reflection(
        plans: PlanEmitter,
        request: d.HandleStimulusRequest,
        pending: tuple[str, ...],
    ) -> None:
        """在本次 InteractionDeadline 的所有回复计划之后追加认知维护计划。"""
        await plans.emit(
            ActionPlanDraft(
                source_stimulus_ids=pending,
                actions=(
                    d.Reflection(
                        action_id=f"{request.request_id}-reflection",
                        prepared_inputs=request.prepared_inputs,
                    ),
                ),
            )
        )

    def _partition_inputs(
        self,
        prepared_inputs: tuple[d.PreprocessedInput, ...],
    ) -> tuple[list[tuple[d.PreprocessedInput, str]], list[str]]:
        """把明确记忆指令与普通对话文本分开，同时保留输入顺序。"""
        prepared_texts = tuple((item, item.text.strip()) for item in prepared_inputs if item.text and item.text.strip())
        memory_items: list[tuple[d.PreprocessedInput, str]] = []
        reply_parts: list[str] = []
        for item, text in prepared_texts:
            memory_content = self._memory_intent.detect(text) if self._memory_intent is not None else None
            if memory_content is None:
                reply_parts.append(text)
            else:
                memory_items.append((item, memory_content))
        return memory_items, reply_parts

    async def _handle_memory_acknowledgement(
        self,
        request: d.HandleStimulusRequest,
        plans: PlanEmitter,
        pending: tuple[str, ...],
        memory_items: list[tuple[d.PreprocessedInput, str]],
        reply_parts: list[str],
    ) -> d.HandlingReport:
        """提交明确记忆，并把提交确认与同批普通文本合成一次回复。"""
        identity = plans.context.identity
        if identity.user_id is None or self._memory_commit is None:
            return _failed_memory_report(request)
        committed_contents: list[str] = []
        for _, memory_content in memory_items:
            revision = await self._memory_commit.commit(
                handling_invocation(request, plans.context),
                content=memory_content,
            )
            if not revision.identifier.strip():
                return _failed_memory_report(request)
            committed_contents.append(memory_content)
        reply_topic = f"{_MEMORY_ACK_REPLY_TOPIC_PREFIX}：{'；'.join(committed_contents)}"
        normal_topic = "\n".join(reply_parts)
        if normal_topic:
            reply_topic = f"{reply_topic}\n{normal_topic}"
        drafts = await self._composition.compose(
            handling_invocation(request, plans.context),
            user_context=plans.context.user.read(),
            reply_topic=reply_topic,
            conversation_history=render_conversation_history(plans.context.conversation.read()),
            memory_queries=(),
            sing_attempts=(),
            excluded_segments=set(),
        )
        await self._deliver(plans, request, pending, drafts, prefix="r")
        return replace(_report(request, consume=True), emitted_plan_ids=tuple(plans.accepted_ids))

    async def _handle_conversation_reply(
        self,
        request: d.HandleStimulusRequest,
        plans: PlanEmitter,
        pending: tuple[str, ...],
        reply_parts: list[str],
    ) -> d.HandlingReport:
        """等待召回完成后生成并交付一轮正式回复。"""
        reply_topic = "\n".join(reply_parts)
        if not reply_topic:
            return replace(_report(request, consume=True), emitted_plan_ids=tuple(plans.accepted_ids))
        plans.set_interruptible(True)
        await plans.emit(
            ActionPlanDraft(
                source_stimulus_ids=pending, actions=(d.StartThinking(action_id=f"{request.request_id}-thinking"),)
            )
        )
        snapshot = plans.context.conversation.read()
        basis = request.interaction.interaction_revision
        staged = await self._composition.compose_staged(
            handling_invocation(request, plans.context),
            user_context=plans.context.user.read(),
            reply_topic=reply_topic,
            conversation_history=render_conversation_history(snapshot),
            memory_queries=(reply_topic,),
            sing_attempts=self._understanding.extract_terms(reply_topic),
            excluded_segments=_recent_sung_segments(snapshot),
        )
        if not staged.awaits_formal:
            return replace(_report(request, consume=True), emitted_plan_ids=tuple(plans.accepted_ids))
        formal = await staged.formal()
        if not _may_emit_formal(request, basis):
            return replace(_report(request, consume=True), emitted_plan_ids=tuple(plans.accepted_ids))
        _attach_recall(plans, request, formal.memory_hits)
        await self._deliver(plans, request, pending, formal.drafts, prefix="r")
        return replace(_report(request, consume=True), emitted_plan_ids=tuple(plans.accepted_ids))

    @staticmethod
    async def _deliver(
        plans: PlanEmitter, request: d.HandleStimulusRequest, pending: tuple[str, ...], drafts, *, prefix: str
    ) -> None:
        """把一组草稿落库并作为一份独立完整计划交付；无可交付行动时不产生计划。"""
        entries, actions = build_reply_delivery(request, tuple(drafts), prefix=prefix)
        if not actions:
            return
        plans.set_interruptible(False)
        if entries:
            await plans.context.conversation.append(entries)
        await plans.emit(ActionPlanDraft(source_stimulus_ids=pending, actions=actions))
