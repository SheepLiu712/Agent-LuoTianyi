"""冷场后的角色决策：通话续聊，聊天优先分享今天的事件，否则根据上下文找话题。"""

from uuid import uuid4

import src.domain.agent as d
from src.agent.handlers.stimulus.proactive import FirstLoginHandler
from src.agent.processing.plan_emitter import ActionPlanDraft
from src.agent.processing.reply_delivery import build_reply_delivery, render_conversation_history
from src.agent.skills.invocation import handling_invocation


class ProactiveSpeechHandler:
    def __init__(self, *, skills, events):
        self._events = events
        self._generation = FirstLoginHandler(prepared_names=(), prepared_speech=None, skills=skills)

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
            topic = FirstLoginHandler._event_topic(event)
            facts = [f"{event.title}：{event.description}"]
        result = await self._generation._generate_reply(
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
        await plans.context.conversation.append(entries)
        if request.cancellation.is_cancelled:
            return FirstLoginHandler._report(request, plans, status=d.HandlingRequestStatus.CANCELLED)
        await plans.emit(ActionPlanDraft(source_stimulus_ids=(stimulus.stimulus_id,), actions=tuple(actions)))
        return FirstLoginHandler._report(request, plans)
