"""按用户确认的半衰期、单次发言和取消语义验证公开计时接口。"""

import pytest

from src.agent.facade import Agent
from src.agent.proactive_timer import ProactivePolicy


class Clock:
    def __init__(self):
        self.now = 0.0
        self.pending = []

    def schedule(self, delay, callback, generation):
        from unittest.mock import Mock

        handle = Mock()
        self.pending.append((self.now + delay, callback, generation, handle))
        return handle

    def advance(self, seconds):
        self.now += seconds
        pending, self.pending = self.pending, []
        for deadline, callback, generation, handle in pending:
            if deadline <= self.now:
                if not handle.cancel.called:
                    callback(generation)
            else:
                self.pending.append((deadline, callback, generation, handle))


def timer(policy=ProactivePolicy(), initial=False):
    clock, received = Clock(), []
    value = Agent(character_id="luotianyi").create_proactive_timer(
        user_id="user",
        on_due=received.append,
        policy=policy,
        initial_opportunity=initial,
        monotonic=lambda: clock.now,
        schedule=clock.schedule,
    )
    return value, clock, received


def test_reply_completion_waits_full_period_and_unanswered_speech_does_not_repeat():
    value, clock, received = timer()
    value.get_user_stimulus()
    clock.advance(10)
    assert not received
    value.start_timer()
    clock.advance(29)
    assert not received
    clock.advance(1)
    assert len(received) == 1
    value.start_timer()
    clock.advance(300)
    assert len(received) == 1
    value.get_user_stimulus()
    value.start_timer()
    clock.advance(30)
    assert len(received) == 2


def test_heat_at_threshold_does_nothing_and_pause_keeps_decay():
    value, clock, received = timer()
    value.get_user_stimulus()
    value.stop_timer()
    clock.advance(30)
    value.start_timer()
    clock.advance(30)
    assert not received  # 60 秒后热度恰为 0.5，必须严格大于阈值。


def test_restart_cancels_old_deadline_and_input_invalidates_issued_stimulus():
    value, clock, received = timer()
    value.get_user_stimulus()
    value.start_timer()
    clock.advance(10)
    value.start_timer()
    clock.advance(20)
    assert not received
    clock.advance(10)
    assert value.is_current(received[0])
    value.get_user_stimulus()
    assert not value.is_current(received[0])


def test_call_initial_opportunity_and_zero_threshold_survive_numeric_underflow():
    value, clock, received = timer(ProactivePolicy(5, 15, 0), initial=True)
    clock.advance(100000)
    value.start_timer()
    clock.advance(5)
    assert len(received) == 1
    value.start_timer()
    clock.advance(5)
    assert len(received) == 1


def test_multiple_messages_add_heat_but_do_not_accumulate_opportunities():
    value, clock, received = timer()
    value.get_user_stimulus()
    value.get_user_stimulus()
    clock.advance(60)
    value.start_timer()
    clock.advance(30)
    assert len(received) == 1
    value.start_timer()
    clock.advance(30)
    assert len(received) == 1


@pytest.mark.parametrize("kwargs", [{"half_life_seconds": 0}, {"threshold": -1}, {"silence_seconds": float("nan")}])
def test_invalid_policy_fails_at_creation(kwargs):
    with pytest.raises(ValueError):
        ProactivePolicy(**kwargs)
