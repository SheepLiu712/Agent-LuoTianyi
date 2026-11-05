"""聊天处理：单条文本预处理与落库，以及批次回复、反思入口。"""

from contextlib import aclosing
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
from src.agent.handlers.reply_skills import ReplySkills
from src.agent.processing.plan_emitter import ActionPlanDraft, PlanEmitter
from src.agent.processing.reply_delivery import render_conversation_history
from src.agent.processing.reply_dispatch import ReplyDelivery
from src.agent.processing.reply_materials import ReplyGenerationResult, enrich_reply_drafts, resolve_song_selection
from src.agent.skills.cognitive import (
    AudioUnderstandingSkill,
    ExplicitMemoryIntentSkill,
    ImageUnderstandingSkill,
    JargonRecognitionSkill,
)
from src.agent.skills.invocation import handling_invocation
from src.agent.skills.memory_retrieval import MemoryQuery
from src.agent.skills.memory_write import MemoryBasis, MemoryFact, MemoryScope, MemoryWriteSkill
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
        text_understanding: JargonRecognitionSkill,
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
                terms = self._text_understanding.recognize(stimulus.text)
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
                terms = self._text_understanding.recognize(machine_text)
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
        skills: ReplySkills,
        memory_intent: ExplicitMemoryIntentSkill | None = None,
        memory_commit: MemoryWriteSkill | None = None,
        reply: ReplyDelivery | None = None,
    ) -> None:
        """注入具名回复能力以及可选的明确记忆识别与提交能力。"""
        self._skills = skills
        self._reply = reply or ReplyDelivery()
        self._memory_intent = memory_intent
        self._memory_commit = memory_commit

    async def _generate_reply(
        self, invocation, *, user_context, reply_topic, conversation_history, excluded_segments=None, on_drafts=None
    ) -> ReplyGenerationResult:
        invocation.require_user_id()
        if invocation.cancellation.is_cancelled:
            return ReplyGenerationResult()
        decision = await self._skills.topic_extraction.extract(reply_topic, conversation_history=conversation_history)
        if invocation.cancellation.is_cancelled:
            return ReplyGenerationResult()
        recalled = (
            await self._skills.retrieval.search(invocation, query=MemoryQuery(decision.memory_queries))
            if decision.memory_queries
            else None
        )
        if invocation.cancellation.is_cancelled:
            return ReplyGenerationResult()
        candidate = (
            await self._skills.singing.select(
                invocation,
                attempts=decision.sing_attempts,
                excluded_segments=excluded_segments,
                emotion_context="\n".join(part for part in (conversation_history, f"当前话题：{reply_topic}") if part),
            )
            if decision.sing_attempts
            else None
        )
        sing_plan, learning_requests = resolve_song_selection(candidate)
        lyrics = ""
        if sing_plan is not None:
            information = self._skills.singing.song_information(
                invocation, song_id=sing_plan[0], segment_id=sing_plan[1]
            )
            if information is None:
                sing_plan = None
            else:
                lyrics = information[2] or ""
        if invocation.cancellation.is_cancelled:
            return ReplyGenerationResult()
        drafts = []
        async with aclosing(
            self._skills.reply.generate(
                invocation.character_id,
                scene="chat",
                user_context=user_context,
                reply_topic=reply_topic,
                conversation_history=conversation_history,
                memory_hits=recalled.render_for_prompt() if recalled is not None else [],
                fact_hits=[],
                sing_plan=sing_plan,
            )
        ) as stream:
            async for draft in stream:
                if invocation.cancellation.is_cancelled:
                    return ReplyGenerationResult()
                drafts.append(draft)
                if on_drafts is not None and sing_plan is None and draft.sing is None:
                    await on_drafts((draft,))
        return ReplyGenerationResult(
            drafts=enrich_reply_drafts(drafts, sing_plan=sing_plan, lyrics=lyrics),
            memory_hits=tuple(recalled.hits) if recalled is not None else (),
            learning_requests=learning_requests,
        )

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
            await self._emit_maintenance(plans, request, pending)
            report = replace(report, emitted_plan_ids=tuple(plans.accepted_ids))
        return report

    @staticmethod
    async def _emit_maintenance(
        plans: PlanEmitter,
        request: d.HandleStimulusRequest,
        pending: tuple[str, ...],
    ) -> None:
        """在本次 InteractionDeadline 的所有回复计划之后追加阈值维护计划。"""
        await plans.emit(
            ActionPlanDraft(
                source_stimulus_ids=pending,
                actions=(
                    d.CognitiveMaintenance(
                        action_id=f"{request.request_id}-maintenance",
                        reason=d.MaintenanceReason.COMPACTION_THRESHOLD,
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
        for item, memory_content in memory_items:
            source = next(
                value for value in request.interaction.pending_stimuli if value.stimulus_id == item.stimulus_id
            )
            revision = await self._memory_commit.commit_fact(
                handling_invocation(request, plans.context),
                fact=MemoryFact(
                    source="explicit_memory",
                    source_id=item.stimulus_id,
                    occurred_at=source.occurred_at,
                    content=memory_content,
                    scope=MemoryScope.USER,
                    basis=MemoryBasis.USER_REQUEST,
                ),
            )
            if not revision.memory_ids or any(not value.strip() for value in revision.memory_ids):
                return _failed_memory_report(request)
            committed_contents.append(memory_content)
        reply_topic = f"{_MEMORY_ACK_REPLY_TOPIC_PREFIX}：{'；'.join(committed_contents)}"
        normal_topic = "\n".join(reply_parts)
        if normal_topic:
            reply_topic = f"{reply_topic}\n{normal_topic}"

        learning_requests = ()

        async def generate(on_drafts):
            nonlocal learning_requests
            result = await self._generate_reply(
                handling_invocation(request, plans.context),
                user_context=plans.context.user.read(),
                reply_topic=reply_topic,
                conversation_history=render_conversation_history(plans.context.conversation.read()),
                excluded_segments=_recent_sung_segments(plans.context.conversation.read()),
                on_drafts=on_drafts,
            )
            learning_requests = result.learning_requests
            return result.drafts

        await self._reply.deliver(request, plans, generate, prefix="r", sources=pending)
        await self._reply.request_learning(request, plans, learning_requests, sources=pending)
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
        learning_requests = ()

        async def generate(on_drafts):
            nonlocal learning_requests
            formal = await self._generate_reply(
                handling_invocation(request, plans.context),
                user_context=plans.context.user.read(),
                reply_topic=reply_topic,
                conversation_history=render_conversation_history(snapshot),
                excluded_segments=_recent_sung_segments(snapshot),
                on_drafts=on_drafts,
            )
            learning_requests = formal.learning_requests
            _attach_recall(plans, request, formal.memory_hits)
            return formal.drafts

        await self._reply.deliver(request, plans, generate, prefix="r", sources=pending)
        await self._reply.request_learning(request, plans, learning_requests, sources=pending)
        return replace(_report(request, consume=True), emitted_plan_ids=tuple(plans.accepted_ids))
