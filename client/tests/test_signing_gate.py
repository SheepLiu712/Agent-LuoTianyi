"""签署门禁的单元测试：五秒前台计时、到底部判定、文案与重置规则。"""

import pytest

from src.gui.signing_gate import (
    STATUS_LOADING,
    STATUS_READY,
    STATUS_READING,
    STATUS_SUBMITTING,
    SigningGate,
    TEXT_BOTTOM_HINT,
    TEXT_CONFIRM,
    TEXT_CONFIRM_WAITING,
    TEXT_LOAD_FAILED,
    TEXT_SUBMITTING,
)


def loaded_gate(**kwargs) -> SigningGate:
    gate = SigningGate(**kwargs)
    gate.mark_loaded()
    gate.resume(now=0.0)
    return gate


def test_loading_state_has_no_hint_and_no_confirm():
    gate = SigningGate()

    assert gate.status == STATUS_LOADING
    assert gate.can_confirm is False
    assert gate.hint_text == ""


def test_confirm_needs_both_five_seconds_and_bottom():
    gate = loaded_gate()

    gate.tick(now=5.0)
    assert gate.remaining_seconds == 0
    assert gate.can_confirm is False
    assert gate.confirm_text == TEXT_CONFIRM
    assert gate.hint_text == TEXT_BOTTOM_HINT

    gate.observe_scroll(value=0, maximum=1000)
    assert gate.can_confirm is False

    gate.observe_scroll(value=998, maximum=1000)  # 容差内视为到底
    assert gate.can_confirm is True
    assert gate.hint_text == ""


def test_bottom_prompts_the_reader_when_time_is_not_up():
    gate = loaded_gate()

    gate.observe_scroll(value=1000, maximum=1000)
    gate.tick(now=1.0)

    assert gate.can_confirm is False
    assert gate.confirm_text == TEXT_CONFIRM_WAITING.format(seconds=4)
    assert gate.hint_text == ""


def test_remaining_seconds_uses_ceiling():
    gate = loaded_gate()

    gate.tick(now=0.2)
    assert gate.remaining_seconds == 5
    gate.tick(now=1.2)
    assert gate.remaining_seconds == 4
    gate.tick(now=4.05)
    assert gate.remaining_seconds == 1


def test_bottom_first_then_time_does_not_require_extra_wait():
    gate = loaded_gate()

    gate.observe_scroll(value=500, maximum=500)  # 1 秒内到底
    gate.tick(now=1.0)
    assert gate.can_confirm is False

    gate.tick(now=5.0)
    assert gate.can_confirm is True


def test_content_that_fits_on_one_screen_satisfies_bottom_immediately():
    gate = loaded_gate()

    gate.observe_scroll(value=0, maximum=0)
    gate.tick(now=5.0)

    assert gate.can_confirm is True


def test_background_time_is_not_counted():
    gate = loaded_gate()
    gate.tick(now=2.0)
    assert gate.remaining_seconds == 3

    gate.pause()
    gate.tick(now=12.0)  # 后台十秒不计入
    gate.resume(now=12.0)
    gate.tick(now=15.0)

    assert gate.remaining_seconds == 0


def test_clock_going_backwards_never_adds_or_removes_time():
    """单调时钟回拨不得增加已读时长；恢复到新读数后按新的前进量继续累计。"""
    gate = loaded_gate()

    gate.tick(now=1.0)
    gate.tick(now=0.5)  # 回拨：负增量一律忽略
    assert gate.elapsed_seconds == pytest.approx(1.0, abs=0.001)

    gate.tick(now=1.5)
    assert gate.elapsed_seconds == pytest.approx(2.0, abs=0.001)
    assert gate.remaining_seconds == 3


def test_reaching_bottom_is_sticky_within_one_open():
    gate = loaded_gate()
    gate.observe_scroll(value=1000, maximum=1000)

    gate.observe_scroll(value=0, maximum=1000)  # 向上回看

    assert gate.reached_bottom is True


def test_scroll_observed_before_loaded_is_ignored():
    gate = SigningGate()

    gate.observe_scroll(value=1000, maximum=1000)

    assert gate.reached_bottom is False


def test_begin_loading_resets_time_and_bottom_for_reopen_or_new_version():
    gate = loaded_gate()
    gate.tick(now=5.0)
    gate.observe_scroll(value=1000, maximum=1000)
    assert gate.can_confirm is True

    gate.begin_loading()
    gate.mark_loaded()
    gate.resume(now=100.0)

    assert gate.status == STATUS_READING
    assert gate.elapsed_seconds == 0
    assert gate.reached_bottom is False
    assert gate.remaining_seconds == 5
    assert gate.can_confirm is False


def test_load_failure_disables_confirm_and_shows_retry_text():
    gate = loaded_gate()

    gate.mark_load_failed()

    assert gate.can_confirm is False
    assert gate.load_failed_text == TEXT_LOAD_FAILED
    assert gate.hint_text == ""


def test_submitting_disables_confirm_and_freezes_timer():
    gate = loaded_gate()
    gate.tick(now=5.0)
    gate.observe_scroll(value=1000, maximum=1000)

    gate.begin_submit()
    assert gate.can_confirm is False
    assert gate.confirm_text == TEXT_SUBMITTING

    gate.tick(now=30.0)
    assert gate.elapsed_seconds == pytest.approx(5.0, abs=0.001)

    gate.end_submit()
    assert gate.status == STATUS_READY
    assert gate.can_confirm is True


def test_failed_submit_keeps_reading_state():
    gate = loaded_gate()
    gate.tick(now=5.0)
    gate.observe_scroll(value=1000, maximum=1000)
    gate.begin_submit()

    gate.end_submit()

    assert gate.reached_bottom is True
    assert gate.remaining_seconds == 0
    assert gate.confirm_text == TEXT_CONFIRM
