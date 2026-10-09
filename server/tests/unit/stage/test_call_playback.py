import pytest

from src.domain.call import CallState
from src.stage._call_playback import CallPlaybackCoordinator, PlaybackSettlementError


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def coordinator():
    clock = Clock()
    return CallPlaybackCoordinator(monotonic=clock), clock


def final_stream(playback, response_id="response", stream_id=1):
    playback.register_stream(response_id, stream_id)
    playback.mark_final_sent(response_id, stream_id)


def test_unknown_or_not_final_stream_cannot_complete():
    playback, _ = coordinator()
    with pytest.raises(PlaybackSettlementError, match="unknown"):
        playback.complete_playback("missing", 1)
    playback.register_stream("response", 1)
    with pytest.raises(PlaybackSettlementError, match="before final"):
        playback.complete_playback("response", 1)


def test_only_last_first_completion_starts_silence_and_duplicate_does_not_reset():
    playback, clock = coordinator()
    final_stream(playback, "response", 1)
    final_stream(playback, "response", 2)
    assert playback.complete_playback("response", 1).silence_started_at is None
    assert playback.complete_playback("response", 2).silence_started_at == 100.0
    clock.now = 103.0
    duplicate = playback.complete_playback("response", 2)
    assert duplicate.duplicate is True and duplicate.silence_started_at == 100.0
    assert playback.silence_elapsed(now=104.999) is False
    assert playback.silence_elapsed(now=105.0) is True


def test_stopped_stream_settles_only_after_explicit_acceptance_and_late_completion_cannot_restart():
    playback, clock = coordinator()
    final_stream(playback)
    playback.set_generation_count(1)
    assert playback.pending_streams == (("response", 1),)
    assert playback.settle_stopped_stream("response", 1) is True
    assert playback.pending_streams == ()
    late = playback.complete_playback("response", 1)
    assert late.duplicate is True and late.silence_started_at is None
    clock.now = 110.0
    playback.set_generation_count(0)
    assert playback.silence_started_at is None


def test_empty_or_cancel_only_call_never_creates_completion_qualification():
    playback, _ = coordinator()
    playback.set_generation_count(1)
    playback.set_generation_count(0)
    playback.set_call_state(CallState.ACTIVE)
    assert playback.silence_started_at is None

    final_stream(playback)
    playback.settle_stopped_stream("response", 1)
    assert playback.silence_started_at is None


@pytest.mark.parametrize("busy", ["pending_send", "generation", "speech", "unfinished_turn"])
def test_new_busy_work_invalidates_old_completion_and_clear_does_not_restart_without_new_completion(busy):
    playback, clock = coordinator()
    setters = {
        "pending_send": playback.set_pending_send_count,
        "generation": playback.set_generation_count,
        "speech": lambda value: playback.set_user_speaking(bool(value)),
        "unfinished_turn": playback.set_unfinished_user_turn_count,
    }
    final_stream(playback, "response", 1)
    playback.complete_playback("response", 1)
    setters[busy](1)
    assert playback.silence_started_at is None
    clock.now = 120.0
    setters[busy](0)
    assert playback.silence_started_at is None

    final_stream(playback, "response", 2)
    playback.complete_playback("response", 2)
    assert playback.silence_started_at == 120.0


def test_new_work_cancels_running_silence_and_new_completion_uses_new_time():
    playback, clock = coordinator()
    final_stream(playback, "response", 1)
    playback.complete_playback("response", 1)
    clock.now = 102.0
    playback.register_stream("response", 2)
    assert playback.silence_started_at is None
    playback.mark_final_sent("response", 2)
    clock.now = 130.0
    playback.complete_playback("response", 2)
    assert playback.silence_started_at == 130.0


def test_reconnecting_blocks_implicit_restart_until_stage_provides_baseline():
    playback, clock = coordinator()
    final_stream(playback)
    playback.complete_playback("response", 1)
    clock.now = 102.0
    playback.set_call_state(CallState.RECONNECTING)
    assert playback.silence_started_at is None
    assert playback.silence_elapsed(now=200.0) is False
    clock.now = 150.0
    playback.set_call_state(CallState.ACTIVE)
    assert playback.silence_started_at is None
    playback.restore_silence_after_reconnect(started_at=150.0)
    assert playback.silence_started_at == 150.0


@pytest.mark.parametrize("state", [CallState.ENDING, CallState.ENDED, CallState.FAILED])
def test_ending_states_cannot_become_silence_eligible(state):
    playback, _ = coordinator()
    final_stream(playback)
    playback.set_call_state(state)
    playback.complete_playback("response", 1)
    assert playback.silence_started_at is None


def test_final_sent_alone_never_counts_as_played():
    playback, _ = coordinator()
    final_stream(playback)
    assert playback.pending_streams == (("response", 1),)
    assert playback.silence_started_at is None


def test_close_clears_all_in_memory_state():
    playback, _ = coordinator()
    final_stream(playback)
    playback.set_pending_send_count(1)
    playback.set_generation_count(1)
    playback.set_user_speaking(True)
    playback.set_unfinished_user_turn_count(1)
    playback.close()
    assert playback.pending_streams == ()
    assert playback.silence_started_at is None
    with pytest.raises(PlaybackSettlementError, match="unknown"):
        playback.complete_playback("response", 1)
