"""Realtime-call stimulus handlers and CALL-only reply planning."""

from __future__ import annotations

from datetime import datetime, timedelta

import src.domain.agent as d
from src.agent.context import ConversationEntry, TextContent
from src.agent.processing.plan_emitter import ActionPlanDraft, PlanEmitter
from src.agent.processing.reply_dispatch import ReplyDelivery
from src.agent.skills.contracts import ReplyDraft
from src.domain.call import (
    CallAnswerDecision,
    CallAudioRoute,
    CallOutcome,
    CallSpeechDelivery,
)
from src.utils.enum_type import ConversationSource


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
    return ReplyDelivery.call_say(request, draft, suffix=suffix, provisional=provisional)


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


class CallReplySegmentReadyHandler:
    def __init__(self, replies):
        self._replies = replies

    async def handle(self, request, plans):
        stimulus = request.stimulus
        if not isinstance(stimulus, d.CallReplySegmentReady):
            raise TypeError("expected CallReplySegmentReady")
        expression, tone = self._replies.expression_for_tone(plans.context.identity.character_id, stimulus.tone)
        action = d.Say(
            action_id=f"{request.request_id}-say",
            message_id=f"{request.request_id}-message",
            content=stimulus.text,
            sound_content=stimulus.text,
            prepared_audio_ref=None,
            tone=d.Tone(value=tone),
            expression=d.ChangeExpression(expression_id=expression) if expression is not None else None,
            delivery=d.OutputDelivery.EPHEMERAL_REACTION,
            call_delivery=CallSpeechDelivery(
                audio_route=CallAudioRoute.CALL,
                display_in_chat=False,
                is_ephemeral=True,
                response_id=f"{stimulus.response_id}-segment-{stimulus.segment_index}",
            ),
        )
        await plans.emit(ActionPlanDraft(source_stimulus_ids=(stimulus.stimulus_id,), actions=(action,)))
        return _with_emitted(request, plans)


class CallMemoryLookupRequestedHandler:
    async def handle(self, request, plans):
        stimulus = request.stimulus
        if not isinstance(stimulus, d.CallMemoryLookupRequested):
            raise TypeError("expected CallMemoryLookupRequested")
        await plans.emit(
            ActionPlanDraft(
                source_stimulus_ids=(stimulus.stimulus_id,),
                actions=(
                    d.LookupCallMemory(
                        action_id=f"{request.request_id}-lookup",
                        response_id=stimulus.response_id,
                        tool_call_id=stimulus.tool_call_id,
                        query=stimulus.query,
                        turn_seq=stimulus.turn_seq,
                    ),
                ),
            )
        )
        return _with_emitted(request, plans)
