"""Realtime-call stimulus handlers and CALL-only reply planning."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

import src.domain.agent as d
from src.agent.context import ConversationEntry, TextContent
from src.agent.processing.plan_emitter import ActionPlanDraft, PlanEmitter
from src.agent.processing.reply_delivery import render_conversation_history
from src.agent.skills.cognitive.call_recall import CallRecallDecisionSkill, CallReplySkill, SilenceDecision
from src.agent.skills.contracts import ReplyDraft
from src.agent.skills.expression.prepared_speech import PreparedSpeechCatalog
from src.agent.skills.invocation import handling_invocation
from src.domain.call import (
    AckStyle,
    CallAnswerDecision,
    CallAudioRoute,
    CallEndReason,
    CallOutcome,
    CallSpeechDelivery,
    RecallMode,
)
from src.utils.enum_type import ConversationSource
from src.utils.logger import get_logger

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
    def __init__(self, replies: CallReplySkill, prepared_speech: PreparedSpeechCatalog) -> None:
        self._replies = replies
        self._prepared_speech = prepared_speech

    async def handle(self, request: d.HandleStimulusRequest, plans: PlanEmitter) -> d.HandlingReport:
        stimulus = request.stimulus
        if not isinstance(stimulus, d.CallStarted):
            raise TypeError("CallStartedHandler requires CallStarted")
        drafts = await _generate_reply(
            self._replies,
            self._prepared_speech,
            "opening",
            plans,
            request,
            handling_invocation(request, plans.context),
            reply_topic="实时语音通话刚刚接通，请用一句简短自然的话向用户打招呼",
            user_context=plans.context.user.read(),
            conversation_history=render_conversation_history(plans.context.conversation.read()),
            memory_pool=(),
        )
        if drafts is None:
            return _failed_report(request, plans)
        await _emit_formal(plans, request, drafts, prefix="opening")
        return _with_emitted(request, plans)


class CallTurnCompletedHandler:
    """Accept a user fact independently of cancellable reply generation."""

    async def handle(self, request: d.HandleStimulusRequest, plans: PlanEmitter) -> d.HandlingReport:
        stimulus = request.stimulus
        if not isinstance(stimulus, d.CallTurnCompleted):
            raise TypeError("CallTurnCompletedHandler requires CallTurnCompleted")
        entry = ConversationEntry(
            entry_id=f"call-turn-{stimulus.turn_seq}-user",
            timestamp=_local_fact_time(request),
            source=ConversationSource.USER.value,
            content=TextContent(stimulus.audio_content.render()),
        )
        await plans.context.conversation.append((entry,))
        return _report(request)


class CallReplyConfirmedHandler:
    async def handle(self, request: d.HandleStimulusRequest, plans: PlanEmitter) -> d.HandlingReport:
        stimulus = request.stimulus
        if not isinstance(stimulus, d.CallReplyConfirmed):
            raise TypeError("CallReplyConfirmedHandler requires CallReplyConfirmed")
        prefix = f"turn-{stimulus.turn_seq}" if stimulus.turn_seq is not None else "proactive"
        entry = ConversationEntry(
            entry_id=f"call-{prefix}-agent-{stimulus.response_id}",
            timestamp=_local_fact_time(request),
            source=ConversationSource.AGENT.value,
            content=TextContent(stimulus.text),
        )
        await plans.context.conversation.append((entry,))
        await _emit_maintenance(plans, request)
        return _with_emitted(request, plans)


class CallReplyRequestedHandler:
    def __init__(
        self, recall: CallRecallDecisionSkill, replies: CallReplySkill, prepared_speech: PreparedSpeechCatalog
    ) -> None:
        self._recall = recall
        self._replies = replies
        self._prepared_speech = prepared_speech

    async def handle(self, request: d.HandleStimulusRequest, plans: PlanEmitter) -> d.HandlingReport:
        stimulus = request.stimulus
        if not isinstance(stimulus, d.CallReplyRequested):
            raise TypeError("CallReplyRequestedHandler requires CallReplyRequested")
        semantic = (
            "\n".join(item.audio_content.render() for item in request.interaction.pending_stimuli)
            or stimulus.audio_content.render()
        )
        if stimulus.interrupted:
            semantic += "\n此前回复被打断。结合已确认播放的对话继续处理所有待回复内容，不要假设未确认部分已被听到。"
        invocation = handling_invocation(request, plans.context)
        history = render_conversation_history(plans.context.conversation.read())
        decision = await self._recall.decide(
            invocation,
            memory_pool=plans.context.call_memory,
            audio_semantic=semantic,
            conversation_history=history,
            user_context=plans.context.user.read(),
        )
        memory_pool = tuple(item.content for item in plans.context.call_memory.snapshot())
        if decision.mode is RecallMode.RECALL:
            await _emit_ack(plans, request, decision.ack_style)
            memory_pool = await self._recall.recall_once(
                invocation,
                memory_pool=plans.context.call_memory,
                queries=decision.memory_queries,
            )
        drafts = await _generate_reply(
            self._replies,
            self._prepared_speech,
            "turn",
            plans,
            request,
            invocation,
            reply_topic=semantic,
            user_context=plans.context.user.read(),
            conversation_history=history,
            memory_pool=memory_pool,
        )
        if drafts is None:
            return _failed_report(request, plans)
        await _emit_formal(plans, request, drafts, prefix=f"turn-{stimulus.turn_seq}")
        pending = tuple(item.stimulus_id for item in request.interaction.pending_stimuli)
        return replace(
            _with_emitted(request, plans), consumed_pending_stimulus_ids=pending, retained_pending_stimulus_ids=()
        )


class CallSilenceElapsedHandler:
    def __init__(
        self, recall: CallRecallDecisionSkill, replies: CallReplySkill, prepared_speech: PreparedSpeechCatalog
    ) -> None:
        self._recall = recall
        self._replies = replies
        self._prepared_speech = prepared_speech

    async def handle(self, request: d.HandleStimulusRequest, plans: PlanEmitter) -> d.HandlingReport:
        stimulus = request.stimulus
        if not isinstance(stimulus, d.CallSilenceElapsed):
            raise TypeError("CallSilenceElapsedHandler requires CallSilenceElapsed")
        invocation = handling_invocation(request, plans.context)
        history = render_conversation_history(plans.context.conversation.read())
        decision = await self._recall.decide_silence(
            invocation,
            memory_pool=plans.context.call_memory,
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
        drafts = await _generate_reply(
            self._replies,
            self._prepared_speech,
            "silence",
            plans,
            request,
            invocation,
            reply_topic=topic,
            user_context=plans.context.user.read(),
            conversation_history=history,
            memory_pool=tuple(item.content for item in plans.context.call_memory.snapshot()),
        )
        if drafts is None:
            return _failed_report(request, plans)
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


class CallTimeLimitWarningHandler:
    """Produce the fixed pre-deadline notice without invoking a generative model."""

    async def handle(self, request: d.HandleStimulusRequest, plans: PlanEmitter) -> d.HandlingReport:
        stimulus = request.stimulus
        if not isinstance(stimulus, d.CallTimeLimitWarning):
            raise TypeError("CallTimeLimitWarningHandler requires CallTimeLimitWarning")
        text = "通话时间快到了，我们很快就要结束啦。"
        action = _call_say(
            request,
            ReplyDraft(content=text, sound_content=text, tone="normal", expression=None),
            suffix="time-limit-warning",
            provisional=False,
        )
        await plans.emit(ActionPlanDraft(source_stimulus_ids=(stimulus.stimulus_id,), actions=(action,)))
        return _with_emitted(request, plans)


class CallEndingHandler:
    """以唯一结束刺激安排一次维护及概要行动。"""

    async def handle(self, request: d.HandleStimulusRequest, plans: PlanEmitter) -> d.HandlingReport:
        stimulus = request.stimulus
        if not isinstance(stimulus, d.CallEnding):
            raise TypeError("CallEndingHandler requires CallEnding")
        if stimulus.user_id is None:
            raise ValueError("call ending requires user identity")
        if stimulus.final_snapshot.terminal.outcome is CallOutcome.CONNECTED:
            await plans.emit(
                ActionPlanDraft(
                    source_stimulus_ids=(stimulus.stimulus_id,),
                    actions=(
                        d.FinalizeCall(
                            action_id=f"{request.request_id}-finalize-call",
                            user_id=stimulus.user_id,
                            final_snapshot=stimulus.final_snapshot,
                        ),
                    ),
                )
            )
        return _with_emitted(request, plans)


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


async def _emit_maintenance(plans: PlanEmitter, request: d.HandleStimulusRequest) -> None:
    await plans.emit(
        ActionPlanDraft(
            source_stimulus_ids=(request.stimulus.stimulus_id,),
            actions=(
                d.CognitiveMaintenance(
                    action_id=f"{request.request_id}-maintenance",
                    reason=d.MaintenanceReason.COMPACTION_THRESHOLD,
                ),
            ),
        )
    )


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


async def _generate_reply(skill, prepared_speech, scene, plans, request, invocation, **kwargs):
    try:
        drafts = await skill.generate(invocation, **kwargs)
        if not drafts:
            raise ValueError("empty call reply")
        return drafts
    except Exception as error:
        get_logger(__name__).warning(
            "Call reply generation failed request_id={} error_type={}", request.request_id, type(error).__name__
        )
        if request.cancellation.is_cancelled:
            return None
        resource = prepared_speech.choose_call_apology(invocation.character_id, scene)
        apology = d.Say(
            action_id=f"{request.request_id}-apology",
            content="",
            sound_content=None,
            prepared_audio_ref=d.MediaRef(media_id=resource.name),
            tone=d.Tone(value="normal"),
            expression=None,
            delivery=d.OutputDelivery.EPHEMERAL_REACTION,
            call_delivery=CallSpeechDelivery(
                audio_route=CallAudioRoute.CALL,
                display_in_chat=False,
                is_ephemeral=True,
                provisional=True,
                response_id=f"{request.request_id}-apology",
            ),
        )
        await plans.emit(ActionPlanDraft(source_stimulus_ids=(request.stimulus.stimulus_id,), actions=(apology,)))
        return None


def _failed_report(request, plans):
    return replace(
        _with_emitted(request, plans),
        request_status=d.HandlingRequestStatus.FAILED,
        error_code=d.HandlingErrorCode.INTERNAL_ERROR,
    )
