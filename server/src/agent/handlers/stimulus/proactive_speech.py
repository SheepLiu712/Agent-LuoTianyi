"""冷场后的角色决策：通话续聊，聊天优先分享今天的事件，否则根据上下文找话题。"""

from contextlib import aclosing
from uuid import uuid4

import src.domain.agent as d
from src.agent.handlers.stimulus.proactive import FirstLoginHandler
from src.agent.processing.plan_emitter import ActionPlanDraft
from src.agent.processing.reply_delivery import build_reply_delivery, render_conversation_history
from src.agent.processing.reply_materials import ReplyGenerationResult, enrich_reply_drafts, resolve_song_selection
from src.agent.skills.invocation import handling_invocation
from src.agent.skills.memory_retrieval import MemoryQuery


class ProactiveSpeechHandler:
    def __init__(self, *, skills, events):
        self._events = events
        self._skills = skills

    async def handle(self, request, plans):
        stimulus = request.stimulus
        if not isinstance(stimulus, d.ProactiveSpeechDue):
            raise TypeError("expected ProactiveSpeechDue")
        plans.set_interruptible(True)
        if isinstance(request.interaction, d.CallInteractionSnapshot):
            await plans.emit(
                ActionPlanDraft(
                    source_stimulus_ids=(stimulus.stimulus_id,),
                    actions=(d.RequestCallSpeech(action_id=str(uuid4()), instruction="silence"),),
                )
            )
            return FirstLoginHandler._report(request, plans)
        identity = plans.context.identity
        events = self._events.list_due(
            character_id=identity.character_id,
            user_id=identity.user_id,
            now=request.interaction.now,
        )
        selected = next(
            (
                event
                for event in events
                if (
                    event.reason in {"holiday", "birthday", "anniversary", "travel", "new_song"}
                    and event.character_id == identity.character_id
                    and not event.is_notified
                    and (not event.is_personal or event.target_user_id == identity.user_id)
                )
            ),
            None,
        )
        topic = "用户暂时没有继续说话。请结合当前对话上下文，自然地延续或寻找一个合适的话题，不要重复上一轮内容。"
        facts = []
        if selected is not None:
            event = d.EventReminder(
                event_id=selected.event_id,
                event_type=selected.reason,
                title=selected.title,
                description=selected.description,
                trigger_key=selected.trigger_key,
            )
            topic = self._event_topic(event)
            facts = [f"{event.title}：{event.description}"]
        result = await self._generate_reply(
            handling_invocation(request, plans.context),
            user_context=plans.context.user.read(),
            reply_topic=topic,
            conversation_history=render_conversation_history(plans.context.conversation.read()),
            fact_hits=facts,
        )
        if request.cancellation.is_cancelled:
            return FirstLoginHandler._report(request, plans, status=d.HandlingRequestStatus.CANCELLED)
        entries, actions = build_reply_delivery(request, result.drafts, prefix="proactive-")
        if not actions:
            raise RuntimeError("主动发言未生成可执行回复")
        if selected is not None:
            actions = (
                *actions,
                d.MarkTopicShared(
                    action_id=str(uuid4()),
                    event_id=selected.event_id,
                    trigger_key=selected.trigger_key,
                ),
            )
        actions = (
            *actions,
            *(
                d.RequestSongLearning(
                    action_id=str(uuid4()),
                    song_id=song,
                    dedup_key=f"song-learning:{identity.character_id}:{song}",
                )
                for song in dict.fromkeys(result.learning_requests)
            ),
        )
        await plans.context.conversation.append(entries)
        if request.cancellation.is_cancelled:
            return FirstLoginHandler._report(request, plans, status=d.HandlingRequestStatus.CANCELLED)
        await plans.emit(ActionPlanDraft(source_stimulus_ids=(stimulus.stimulus_id,), actions=tuple(actions)))
        return FirstLoginHandler._report(request, plans)

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
                scene="chat",
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
