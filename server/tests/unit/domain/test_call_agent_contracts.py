from datetime import datetime, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

import src.domain.agent as d
from src.domain.call import (
    CallAnswerDecision,
    CallAudioRoute,
    CallAudioSemantic,
    CallEndReason,
    CallFinalSnapshot,
    CallFinalTurn,
    CallOutcome,
    CallReplyStatus,
    CallSpeechDelivery,
    CallState,
    CallTerminalFacts,
)


def stimulus_fields(now):
    return dict(
        stimulus_id="stimulus-1",
        schema_version=1,
        occurred_at=now,
        source=d.StimulusSource.STAGE,
        target_character_ids=("luotianyi",),
        user_id="user",
        ephemeral=True,
    )


def test_call_stimuli_snapshot_and_handle_request_form_runtime_closed_loop():
    call_id = uuid4()
    now = datetime.now(timezone.utc)
    common = stimulus_fields(now)
    answer = d.CallAnswerRequested(**common, call_id=call_id, requested_at=now)
    started = d.CallStarted(**common, call_id=call_id, connected_at=now)
    turn = d.CallTurnCompleted(**common, call_id=call_id, turn_seq=1, audio_content=CallAudioSemantic(emotion="开心"))
    silence = d.CallSilenceElapsed(**common, call_id=call_id, silence_ms=5000)
    terminal = CallTerminalFacts(call_id, CallOutcome.CONNECTED, CallEndReason.USER_HANGUP, 1234, now)
    final = CallFinalSnapshot(
        terminal=terminal,
        completed_turns=(CallFinalTurn(1, "情绪：开心", CallReplyStatus.COMPLETED, "你好"),),
        maintenance_turn_seq=0,
    )
    ending = d.CallEnding(**common, call_id=call_id, reason=CallEndReason.USER_HANGUP, final_snapshot=final)
    snapshot = d.CallInteractionSnapshot(
        interaction_id=str(call_id),
        interaction_revision=1,
        user_id="user",
        pending_stimuli=(),
        now=now,
        timezone=ZoneInfo("Asia/Shanghai"),
        supported_outputs=frozenset({d.AgentOutputKind.AUDIO_CHUNK, d.AgentOutputKind.EXPRESSION}),
        call_id=call_id,
        state=CallState.ACTIVE,
        connection_state=d.ConnectionState.CONNECTED,
    )
    request = d.HandleStimulusRequest(
        request_id="request-1",
        stimulus=started,
        interaction=snapshot,
        cancellation=d.CancellationToken(),
    )

    assert all(isinstance(value, d.Stimulus) for value in (answer, started, turn, silence, ending))
    assert isinstance(request.interaction, d.InteractionSnapshot)
    assert turn.audio_content.render() == "情绪：开心"


def test_answer_request_is_distinct_from_started_and_answer_action_has_plan_identity():
    call_id = uuid4()
    now = datetime.now(timezone.utc)
    common = stimulus_fields(now)
    assert not isinstance(d.CallAnswerRequested(**common, call_id=call_id, requested_at=now), d.CallStarted)
    action = d.AnswerCall(action_id="answer-1", call_id=call_id, decision=CallAnswerDecision.ACCEPT)
    plan = d.ActionPlan(
        plan_id="plan-1",
        origin_request_id="request-1",
        plan_ordinal=0,
        target_character_id="luotianyi",
        interaction_id=str(call_id),
        basis_interaction_revision=0,
        source_stimulus_ids=("stimulus-1",),
        actions=(action,),
    )
    assert action.kind is d.ActionKind.ANSWER_CALL
    assert plan.actions == (action,)


def test_call_speech_delivery_requires_hidden_ephemeral_response_scope_but_chat_defaults_remain():
    assert CallSpeechDelivery().audio_route is CallAudioRoute.CHAT
    call = CallSpeechDelivery(
        audio_route=CallAudioRoute.CALL,
        display_in_chat=False,
        is_ephemeral=True,
        provisional=True,
        response_id="response-1",
    )
    say = d.Say(
        action_id="say-1",
        content="你好",
        sound_content="你好",
        prepared_audio_ref=None,
        tone=d.Tone(value="normal"),
        expression=None,
        delivery=d.OutputDelivery.CONVERSATION,
        call_delivery=call,
    )
    assert say.call_delivery == call
    with pytest.raises(ValueError, match="CALL delivery"):
        CallSpeechDelivery(audio_route=CallAudioRoute.CALL, response_id="response-1")


def test_final_snapshot_accepts_only_completed_formal_turns_and_is_immutable():
    terminal = CallTerminalFacts(
        uuid4(),
        CallOutcome.CONNECTED,
        CallEndReason.USER_HANGUP,
        1234,
        datetime.now(timezone.utc),
    )
    turn = CallFinalTurn(1, "用户说：“你好”", CallReplyStatus.INTERRUPTED, "你好呀")
    snapshot = CallFinalSnapshot(terminal, (turn,), 1)

    assert snapshot.completed_turns == (turn,)
    assert CallFinalTurn(2, "用户说：“未回答”", CallReplyStatus.NOT_STARTED, None).formal_agent_text is None
    assert CallFinalTurn(3, "用户说：“失败”", CallReplyStatus.FAILED, None).formal_agent_text is None
    assert CallFinalTurn(4, "用户说：“打断”", CallReplyStatus.INTERRUPTED, None).formal_agent_text is None
    with pytest.raises(ValueError, match="requires formal"):
        CallFinalTurn(5, "用户说：“完成”", CallReplyStatus.COMPLETED, None)
    with pytest.raises(ValueError, match="cannot contain"):
        CallFinalTurn(6, "用户说：“未回答”", CallReplyStatus.NOT_STARTED, "占位语")
    with pytest.raises(AttributeError):
        snapshot.maintenance_turn_seq = 2


def test_end_call_and_call_contract_validation():
    action = d.EndCall(action_id="end-1", reason=CallEndReason.AGENT_HANGUP)
    assert action.kind is d.ActionKind.END_CALL
    with pytest.raises(ValueError, match="requires"):
        CallAudioSemantic()
    with pytest.raises(Exception):
        d.CallStarted(
            **stimulus_fields(datetime.now(timezone.utc)),
            call_id=uuid4(),
            connected_at=datetime.now(),
        )
