"""Realtime-call stimulus handlers and CALL-only reply planning."""

from __future__ import annotations

from datetime import datetime, timedelta

import src.domain.agent as d
from src.agent.context import ConversationEntry, TextContent
from src.agent.processing.plan_emitter import ActionPlanDraft, PlanEmitter
from src.agent.processing.reply_delivery import render_conversation_history
from src.agent.skills.cognitive.call_recall import CallRecallDecisionSkill, CallReplySkill, SilenceDecision
from src.agent.skills.contracts import ReplyDraft
from src.agent.skills.invocation import handling_invocation
from src.domain.call import AckStyle, CallAnswerDecision, CallAudioRoute, CallEndReason, CallSpeechDelivery, RecallMode
from src.utils.enum_type import ConversationSource

_ACK_TEXT = {
    AckStyle.THINKING: "嗯，让我想想。",
    AckStyle.EMPATHY: "嗯，我在听。",
    AckStyle.CONFIRMING: "好，我想起来了。",
}


def _report(request: d.HandleStimulusRequest) -> d.HandlingReport:
    pending = tuple(item.stimulus_id for item in request.interaction.pending_stimuli)
    return d.HandlingReport(
        request_id=request.request_id,
        trigger_stimulus_id=request.stimulus.stimulus_id,
        basis_interaction_revision=request.interaction.interaction_revision,
        request_status=d.HandlingRequestStatus.COMPLETED,
        considered_pending_stimulus_ids=pending,
        consumed_pending_stimulus_ids=(),
        retained_pending_stimulus_ids=pending,
        emitted_plan_ids=(),
        error_code=None,
        retryable=False,
    )


def _call_say(
    request: d.HandleStimulusRequest,
    draft: ReplyDraft,
    *,
    suffix: str,
    provisional: bool,
) -> d.Say:
    return d.Say(
        action_id=f"{request.request_id}-{suffix}",
        content=draft.content,
        sound_content=draft.sound_content,
        prepared_audio_ref=None,
        tone=d.Tone(value=draft.tone or "normal"),
        expression=d.ChangeExpression(expression_id=draft.expression) if draft.expression else None,
        delivery=d.OutputDelivery.EPHEMERAL_REACTION,
        message_id=None,
        call_delivery=CallSpeechDelivery(
            audio_route=CallAudioRoute.CALL,
            display_in_chat=False,
            is_ephemeral=True,
            provisional=provisional,
            response_id=f"{request.request_id}-{suffix}",
        ),
    )


class CallAnswerRequestedHandler:
    """First-version answer policy accepts calls while retaining an explicit decline action."""

    def __init__(self, *, accept: bool = True) -> None:
        self._decision = CallAnswerDecision.ACCEPT if accept else CallAnswerDecision.DECLINE

    async def handle(self, request: d.HandleStimulusRequest, plans: PlanEmitter) -> d.HandlingReport:
        stimulus = request.stimulus
        if not isinstance(stimulus, d.CallAnswerRequested):
            raise TypeError("CallAnswerRequestedHandler requires CallAnswerRequested")
        await plans.emit(
            ActionPlanDraft(
                source_stimulus_ids=(stimulus.stimulus_id,),
                actions=(
                    d.AnswerCall(
                        action_id=f"{request.request_id}-answer",
                        call_id=stimulus.call_id,
                        decision=self._decision,
                    ),
                ),
            )
        )
        return _with_emitted(request, plans)


class CallStartedHandler:
    def __init__(self, replies: CallReplySkill) -> None:
        self._replies = replies

    async def handle(self, request: d.HandleStimulusRequest, plans: PlanEmitter) -> d.HandlingReport:
        stimulus = request.stimulus
        if not isinstance(stimulus, d.CallStarted):
            raise TypeError("CallStartedHandler requires CallStarted")
        drafts = await self._replies.generate(
            handling_invocation(request, plans.context),
            reply_topic="实时语音通话刚刚接通，请用一句简短自然的话向用户打招呼",
            user_context=plans.context.user.read(),
            conversation_history=render_conversation_history(plans.context.conversation.read()),
            memory_pool=(),
        )
        await _append_agent_entries(plans, "opening", drafts, request)
        await _emit_formal(plans, request, drafts, prefix="opening")
        return _with_emitted(request, plans)


class CallTurnCompletedHandler:
    def __init__(self, recall: CallRecallDecisionSkill, replies: CallReplySkill) -> None:
        self._recall = recall
        self._replies = replies

    async def handle(self, request: d.HandleStimulusRequest, plans: PlanEmitter) -> d.HandlingReport:
        stimulus = request.stimulus
        if not isinstance(stimulus, d.CallTurnCompleted):
            raise TypeError("CallTurnCompletedHandler requires CallTurnCompleted")
        semantic = stimulus.audio_content.render()
        user_entry = ConversationEntry(
            entry_id=f"call-turn-{stimulus.turn_seq}-user",
            timestamp=_local_fact_time(request),
            source=ConversationSource.USER.value,
            content=TextContent(semantic),
        )
        await plans.context.conversation.append((user_entry,))
        invocation = handling_invocation(request, plans.context)
        history = render_conversation_history(plans.context.conversation.read())
        decision = await self._recall.decide(
            invocation,
            call_id=stimulus.call_id,
            audio_semantic=semantic,
            conversation_history=history,
            user_context=plans.context.user.read(),
        )
        memory_pool = self._recall.pool_texts(stimulus.call_id)
        if decision.mode is RecallMode.RECALL:
            await _emit_ack(plans, request, decision.ack_style)
            memory_pool = await self._recall.recall_once(
                invocation,
                call_id=stimulus.call_id,
                queries=decision.memory_queries,
            )
        drafts = await self._replies.generate(
            invocation,
            reply_topic=semantic,
            user_context=plans.context.user.read(),
            conversation_history=history,
            memory_pool=memory_pool,
        )
        await _append_formal_reply(plans, stimulus.turn_seq, drafts, request)
        await _emit_formal(plans, request, drafts, prefix=f"turn-{stimulus.turn_seq}")
        return _with_emitted(request, plans)


class CallSilenceElapsedHandler:
    def __init__(self, recall: CallRecallDecisionSkill, replies: CallReplySkill) -> None:
        self._recall = recall
        self._replies = replies

    async def handle(self, request: d.HandleStimulusRequest, plans: PlanEmitter) -> d.HandlingReport:
        stimulus = request.stimulus
        if not isinstance(stimulus, d.CallSilenceElapsed):
            raise TypeError("CallSilenceElapsedHandler requires CallSilenceElapsed")
        invocation = handling_invocation(request, plans.context)
        history = render_conversation_history(plans.context.conversation.read())
        decision = await self._recall.decide_silence(
            invocation,
            call_id=stimulus.call_id,
            silence_ms=stimulus.silence_ms,
            conversation_history=history,
        )
        if decision is SilenceDecision.WAIT:
            return _report(request)
        topic = (
            "通话中短暂安静了，请自然地继续话题或关心用户，不要提及计时器"
            if decision is SilenceDecision.SPEAK
            else "请用一句自然简短的告别结束这次实时语音通话"
        )
        drafts = await self._replies.generate(
            invocation,
            reply_topic=topic,
            user_context=plans.context.user.read(),
            conversation_history=history,
            memory_pool=self._recall.pool_texts(stimulus.call_id),
        )
        await _append_agent_entries(plans, "silence", drafts, request)
        actions = tuple(
            _call_say(request, draft, suffix=f"silence-{index}", provisional=False)
            for index, draft in enumerate(drafts)
        )
        if decision is SilenceDecision.END_CALL:
            actions = (
                *actions,
                d.EndCall(action_id=f"{request.request_id}-end-call", reason=CallEndReason.AGENT_HANGUP),
            )
        if actions:
            await plans.emit(ActionPlanDraft(source_stimulus_ids=(stimulus.stimulus_id,), actions=actions))
        return _with_emitted(request, plans)


class CallEndingHandler:
    """Acknowledge frozen terminal facts; CL-10 owns settlement, maintenance, and release."""

    async def handle(self, request: d.HandleStimulusRequest, plans: PlanEmitter) -> d.HandlingReport:
        stimulus = request.stimulus
        if not isinstance(stimulus, d.CallEnding):
            raise TypeError("CallEndingHandler requires CallEnding")
        _ = plans, stimulus.final_snapshot
        return _report(request)


async def _emit_ack(plans: PlanEmitter, request: d.HandleStimulusRequest, style: AckStyle) -> None:
    text = _ACK_TEXT.get(style)
    if text is None:
        return
    draft = ReplyDraft(content=text, sound_content=text, tone="normal", expression=None)
    await plans.emit(
        ActionPlanDraft(
            source_stimulus_ids=(request.stimulus.stimulus_id,),
            actions=(_call_say(request, draft, suffix="recall-ack", provisional=True),),
        )
    )


async def _emit_formal(
    plans: PlanEmitter,
    request: d.HandleStimulusRequest,
    drafts: tuple[ReplyDraft, ...],
    *,
    prefix: str,
) -> None:
    actions = tuple(
        _call_say(request, draft, suffix=f"{prefix}-{index}", provisional=False) for index, draft in enumerate(drafts)
    )
    if actions:
        await plans.emit(ActionPlanDraft(source_stimulus_ids=(request.stimulus.stimulus_id,), actions=actions))


async def _append_formal_reply(
    plans: PlanEmitter,
    turn_seq: int,
    drafts: tuple[ReplyDraft, ...],
    request: d.HandleStimulusRequest,
) -> None:
    await _append_agent_entries(plans, f"turn-{turn_seq}", drafts, request)


async def _append_agent_entries(
    plans: PlanEmitter,
    entry_prefix: str,
    drafts: tuple[ReplyDraft, ...],
    request: d.HandleStimulusRequest,
) -> None:
    entries = tuple(
        ConversationEntry(
            entry_id=f"call-{entry_prefix}-agent-{index}",
            timestamp=_local_fact_time(request, offset=index + 1),
            source=ConversationSource.AGENT.value,
            content=TextContent(draft.content),
        )
        for index, draft in enumerate(drafts)
    )
    if entries:
        await plans.context.conversation.append(entries)


def _local_fact_time(request: d.HandleStimulusRequest, *, offset: int = 0) -> datetime:
    base = request.interaction.now.astimezone().replace(tzinfo=None)
    return base + timedelta(microseconds=request.interaction.interaction_revision * 10 + offset)


def _with_emitted(request: d.HandleStimulusRequest, plans: PlanEmitter) -> d.HandlingReport:
    report = _report(request)
    return d.HandlingReport(
        request_id=report.request_id,
        trigger_stimulus_id=report.trigger_stimulus_id,
        basis_interaction_revision=report.basis_interaction_revision,
        request_status=report.request_status,
        considered_pending_stimulus_ids=report.considered_pending_stimulus_ids,
        consumed_pending_stimulus_ids=report.consumed_pending_stimulus_ids,
        retained_pending_stimulus_ids=report.retained_pending_stimulus_ids,
        emitted_plan_ids=tuple(plans.accepted_ids),
        error_code=None,
        retryable=False,
    )
