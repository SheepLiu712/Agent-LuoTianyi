"""主动刺激处理器。"""

from contextlib import aclosing
from datetime import datetime
from uuid import uuid4

import src.domain.agent as d
from src.agent.context import ConversationEntry, TextContent
from src.agent.handlers.reply_skills import ReplySkills
from src.agent.processing.plan_emitter import ActionPlanDraft, PlanEmitter
from src.agent.processing.reply_delivery import render_conversation_history
from src.agent.processing.reply_dispatch import ReplyDelivery
from src.agent.processing.reply_materials import ReplyGenerationResult, enrich_reply_drafts, resolve_song_selection
from src.agent.skills.expression.prepared_speech import PreparedSpeechCatalog
from src.agent.skills.invocation import handling_invocation
from src.agent.skills.memory_retrieval import MemoryQuery
from src.utils.logger import get_logger


class FirstLoginHandler:
    """按配置顺序持久化并交付首次登录预制欢迎。"""

    def __init__(
        self,
        *,
        prepared_names: tuple[str, ...],
        prepared_speech: PreparedSpeechCatalog,
        skills: ReplySkills,
        reply: ReplyDelivery | None = None,
    ) -> None:
        self._prepared_names = prepared_names
        self._prepared_speech = prepared_speech
        self._skills = skills
        self._reply = reply or ReplyDelivery()
        self._logger = get_logger(__name__)

    async def _generate_reply(
        self,
        invocation,
        *,
        user_context,
        reply_topic,
        conversation_history,
        fact_hits,
        excluded_segments=None,
        on_drafts=None,
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
                user_context=user_context,
                reply_topic=reply_topic,
                conversation_history=conversation_history,
                memory_hits=recalled.render_for_prompt() if recalled is not None else [],
                fact_hits=fact_hits,
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

    async def handle(
        self,
        request: d.HandleStimulusRequest,
        plans: PlanEmitter,
    ) -> d.HandlingReport:
        """处理首次欢迎或到期提醒，并把内容交付为正常 Say 计划。"""
        stimulus = request.stimulus
        if not isinstance(stimulus, d.ProactivePromptDue):
            raise TypeError("FirstLoginHandler requires ProactivePromptDue")
        if stimulus.reason.value != "first_login":
            context = plans.context
            plans.set_interruptible(True)
            learning_requests = ()

            async def generate(on_drafts):
                nonlocal learning_requests
                result = await self._generate_reply(
                    handling_invocation(request, context),
                    user_context=context.user.read(),
                    reply_topic=self._reminder_topic(stimulus),
                    fact_hits=[f"{event.title}：{event.description}" for event in stimulus.events],
                    conversation_history=render_conversation_history(context.conversation.read()),
                    excluded_segments=set(),
                    on_drafts=on_drafts,
                )
                learning_requests = result.learning_requests
                return result.drafts

            await self._reply.deliver(
                request,
                plans,
                generate,
                prefix="reminder",
                sources=(stimulus.stimulus_id,),
            )
            await self._reply.request_learning(request, plans, learning_requests, sources=(stimulus.stimulus_id,))
            return self._report(request, plans)

        for name in self._prepared_names:
            try:
                prepared = self._prepared_speech.get(plans.context.identity.character_id, name)
            except KeyError:
                self._logger.error(
                    "First-login prepared speech missing name=%s request_id=%s",
                    name,
                    request.request_id,
                )
                return self._report(
                    request,
                    plans,
                    status=d.HandlingRequestStatus.FAILED,
                    error_code=d.HandlingErrorCode.DEPENDENCY_UNAVAILABLE,
                )

            await plans.context.conversation.append(
                (
                    ConversationEntry(
                        entry_id=str(uuid4()),
                        timestamp=datetime.now(),  # noqa: DTZ005 - conversation storage uses local naive timestamps
                        source="agent",
                        content=TextContent(prepared.text),
                    ),
                )
            )
            await plans.emit(
                ActionPlanDraft(
                    source_stimulus_ids=(stimulus.stimulus_id,),
                    actions=(
                        d.Say(
                            action_id=str(uuid4()),
                            content=prepared.text,
                            sound_content=None,
                            prepared_audio_ref=d.MediaRef(media_id=name),
                            tone=d.Tone(value="normal"),
                            expression=d.ChangeExpression(expression_id="normal"),
                            delivery=d.OutputDelivery.CONVERSATION,
                        ),
                    ),
                )
            )

        return self._report(request, plans)

    @staticmethod
    def _reminder_topic(stimulus: d.ProactivePromptDue) -> str:
        """从 Stage 提供的提醒事实生成只供角色回复生成器使用的内部话题。"""
        if not stimulus.events:
            raise ValueError("主动提醒缺少事件正文")
        return "\n".join(FirstLoginHandler._event_topic(event) for event in stimulus.events)

    @staticmethod
    def _event_topic(event: d.EventReminder) -> str:
        when = {
            "1_day_after": "昨天",
            "day_of_event": "今天",
            "1_day_before": "明天",
            "3_days_before": "3天后",
            "7_days_before": "7天后",
            "1_hour_before": "稍后",
        }[event.trigger_key]
        if event.event_type == "travel":
            return f"你{when}去了{event.title}，请结合具体见闻，自然地向用户分享经历和感受。"
        if event.event_type == "new_song":
            if not event.description.strip():
                raise ValueError(f"新歌提醒缺少歌曲内容：{event.event_id}")
            return f"你{when}学了{event.description}，请自然地向用户分享学会这些歌曲的消息。"
        if event.event_type in {"holiday", "birthday", "anniversary"}:
            return f"{when}是{event.title}，请结合这一天的具体意义送上祝福，并关心用户的安排。"
        raise ValueError(f"不支持的主动提醒类型：{event.event_type}")

    @staticmethod
    def _report(
        request: d.HandleStimulusRequest,
        plans: PlanEmitter,
        *,
        status: d.HandlingRequestStatus = d.HandlingRequestStatus.COMPLETED,
        error_code: d.HandlingErrorCode | None = None,
    ) -> d.HandlingReport:
        return d.HandlingReport(
            request_id=request.request_id,
            trigger_stimulus_id=request.stimulus.stimulus_id,
            basis_interaction_revision=request.interaction.interaction_revision,
            request_status=status,
            considered_pending_stimulus_ids=(),
            consumed_pending_stimulus_ids=(),
            retained_pending_stimulus_ids=(),
            emitted_plan_ids=tuple(plans.accepted_ids),
            retryable=False,
            error_code=error_code,
        )
