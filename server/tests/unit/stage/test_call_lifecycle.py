import pytest

from src.domain.call import CallEndReason, CallOutcome, CallState
from src.stage.call_lifecycle import CallLifecycle, InvalidCallTransition


def test_connected_call_can_reconnect_and_end():
    lifecycle = CallLifecycle()
    lifecycle.transition(CallState.RINGING)
    lifecycle.transition(CallState.ACTIVE)
    lifecycle.transition(CallState.RECONNECTING)
    lifecycle.transition(CallState.ACTIVE)
    lifecycle.transition(CallState.ENDING)
    result = lifecycle.transition(
        CallState.ENDED,
        outcome=CallOutcome.CONNECTED,
        end_reason=CallEndReason.USER_HANGUP,
    )

    assert result.state is CallState.ENDED
    assert (
        lifecycle.transition(
            CallState.ENDED,
            outcome=CallOutcome.CONNECTED,
            end_reason=CallEndReason.USER_HANGUP,
        )
        is result
    )


def test_declined_call_has_explicit_business_result():
    lifecycle = CallLifecycle()
    lifecycle.transition(CallState.RINGING)
    lifecycle.transition(
        CallState.DECLINED,
        outcome=CallOutcome.DECLINED,
        end_reason=CallEndReason.DECLINED,
    )
    result = lifecycle.transition(
        CallState.ENDED,
        outcome=CallOutcome.DECLINED,
        end_reason=CallEndReason.DECLINED,
    )
    assert result.outcome is CallOutcome.DECLINED


def test_setup_failure_is_terminal_and_not_recordable():
    lifecycle = CallLifecycle()
    result = lifecycle.transition(CallState.FAILED, end_reason=CallEndReason.SYSTEM_FAILURE)
    assert result.outcome is None
    with pytest.raises(InvalidCallTransition):
        lifecycle.transition(CallState.PREPARING)


def test_outcome_must_match_whether_call_ever_connected():
    before_answer = CallLifecycle()
    before_answer.transition(CallState.ENDING)
    with pytest.raises(InvalidCallTransition, match="prior ACTIVE"):
        before_answer.transition(
            CallState.ENDED,
            outcome=CallOutcome.CONNECTED,
            end_reason=CallEndReason.USER_HANGUP,
        )

    connected = CallLifecycle()
    connected.transition(CallState.RINGING)
    connected.transition(CallState.ACTIVE)
    connected.transition(CallState.ENDING)
    with pytest.raises(InvalidCallTransition, match="pre-answer"):
        connected.transition(
            CallState.ENDED,
            outcome=CallOutcome.CANCELLED_BEFORE_ANSWER,
            end_reason=CallEndReason.USER_HANGUP,
        )


def test_illegal_transition_and_terminal_fact_change_are_rejected():
    lifecycle = CallLifecycle()
    with pytest.raises(InvalidCallTransition):
        lifecycle.transition(CallState.ACTIVE)
    lifecycle.transition(CallState.ENDING)
    lifecycle.transition(
        CallState.ENDED,
        outcome=CallOutcome.CANCELLED_BEFORE_ANSWER,
        end_reason=CallEndReason.USER_HANGUP,
    )
    with pytest.raises(InvalidCallTransition):
        lifecycle.transition(
            CallState.ENDED,
            outcome=CallOutcome.CONNECTED,
            end_reason=CallEndReason.USER_HANGUP,
        )
