"""CallStage future seam for playback settlement and silence eligibility."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from src.domain.call import CallState

_SILENCE_SECONDS = 5.0


class PlaybackSettlementError(ValueError):
    """The client tried to settle a stream that is not completable."""


@dataclass(frozen=True, slots=True)
class PlaybackCompletion:
    accepted: bool
    duplicate: bool
    silence_started_at: float | None


@dataclass(slots=True)
class _Stream:
    final_sent: bool = False
    cancelled: bool = False
    completed: bool = False


class CallPlaybackCoordinator:
    """Tracks server utterances and exposes silence eligibility without timers or I/O."""

    def __init__(self, *, monotonic: Callable[[], float] = time.monotonic) -> None:
        self._monotonic = monotonic
        self._streams: dict[tuple[str, int], _Stream] = {}
        self._pending_send = 0
        self._generating = 0
        self._user_speaking = False
        self._unfinished_user_turns = 0
        self._state = CallState.ACTIVE
        self._silence_started_at: float | None = None
        self._has_completion_qualification = False
        self._reconnect_resume_required = False

    @property
    def silence_started_at(self) -> float | None:
        return self._silence_started_at

    @property
    def pending_streams(self) -> tuple[tuple[str, int], ...]:
        return tuple(key for key, stream in self._streams.items() if not stream.completed and not stream.cancelled)

    def register_stream(self, response_id: str, stream_id: int) -> None:
        key = self._identity(response_id, stream_id)
        if key in self._streams:
            raise PlaybackSettlementError("playback stream is already registered")
        self._streams[key] = _Stream()
        self._invalidate_silence_qualification()

    def mark_final_sent(self, response_id: str, stream_id: int) -> None:
        stream = self._require_stream(response_id, stream_id)
        if not stream.cancelled and not stream.completed:
            stream.final_sent = True

    def settle_stopped_stream(self, response_id: str, stream_id: int) -> bool:
        """Settle a stream only after CallStage accepted playback.stopped."""
        stream = self._require_stream(response_id, stream_id)
        if stream.cancelled or stream.completed:
            return False
        stream.cancelled = True
        self._refresh_silence()
        return True

    def complete_playback(self, response_id: str, stream_id: int) -> PlaybackCompletion:
        stream = self._require_stream(response_id, stream_id)
        if stream.cancelled or stream.completed:
            return PlaybackCompletion(True, True, self._silence_started_at)
        if not stream.final_sent:
            raise PlaybackSettlementError("playback cannot complete before final was sent")
        stream.completed = True
        self._has_completion_qualification = True
        return PlaybackCompletion(True, False, self._refresh_silence())

    def set_pending_send_count(self, count: int) -> None:
        value = self._count(count, "pending_send_count")
        if value > 0:
            self._invalidate_silence_qualification()
        self._pending_send = value
        self._refresh_silence()

    def set_generation_count(self, count: int) -> None:
        value = self._count(count, "generation_count")
        if value > 0:
            self._invalidate_silence_qualification()
        self._generating = value
        self._refresh_silence()

    def set_user_speaking(self, speaking: bool) -> None:
        if not isinstance(speaking, bool):
            raise TypeError("speaking must be bool")
        if speaking:
            self._invalidate_silence_qualification()
        self._user_speaking = speaking
        self._refresh_silence()

    def set_unfinished_user_turn_count(self, count: int) -> None:
        value = self._count(count, "unfinished_user_turn_count")
        if value > 0:
            self._invalidate_silence_qualification()
        self._unfinished_user_turns = value
        self._refresh_silence()

    def set_call_state(self, state: CallState) -> None:
        if not isinstance(state, CallState):
            raise TypeError("state must be CallState")
        self._state = state
        if state is CallState.RECONNECTING:
            self._silence_started_at = None
            self._reconnect_resume_required = True
        self._refresh_silence()

    def restore_silence_after_reconnect(self, *, started_at: float) -> None:
        """Apply a future CallStage-selected baseline; this component does not choose reconnect policy."""
        if self._state is not CallState.ACTIVE:
            raise PlaybackSettlementError("silence can only resume while call is active")
        if not self._reconnect_resume_required:
            raise PlaybackSettlementError("no reconnect silence baseline is pending")
        if not isinstance(started_at, (int, float)):
            raise TypeError("started_at must be monotonic seconds")
        if not self._is_silence_eligible(ignore_reconnect=True):
            raise PlaybackSettlementError("call is not eligible for resumed silence")
        self._silence_started_at = float(started_at)
        self._reconnect_resume_required = False

    def silence_elapsed(self, *, now: float | None = None) -> bool:
        if self._silence_started_at is None or self._state is not CallState.ACTIVE:
            return False
        current = self._monotonic() if now is None else now
        return current - self._silence_started_at >= _SILENCE_SECONDS

    def close(self) -> None:
        self._streams.clear()
        self._pending_send = 0
        self._generating = 0
        self._user_speaking = False
        self._unfinished_user_turns = 0
        self._silence_started_at = None
        self._has_completion_qualification = False
        self._reconnect_resume_required = False

    def _refresh_silence(self) -> float | None:
        if not self._is_silence_eligible():
            self._silence_started_at = None
        elif self._silence_started_at is None and not self._reconnect_resume_required:
            self._silence_started_at = self._monotonic()
        return self._silence_started_at

    def _is_silence_eligible(self, *, ignore_reconnect: bool = False) -> bool:
        return (
            self._state is CallState.ACTIVE
            and self._has_completion_qualification
            and (ignore_reconnect or not self._reconnect_resume_required)
            and not self.pending_streams
            and self._pending_send == 0
            and self._generating == 0
            and not self._user_speaking
            and self._unfinished_user_turns == 0
        )

    def _invalidate_silence_qualification(self) -> None:
        self._has_completion_qualification = False
        self._silence_started_at = None

    def _require_stream(self, response_id: str, stream_id: int) -> _Stream:
        key = self._identity(response_id, stream_id)
        try:
            return self._streams[key]
        except KeyError as error:
            raise PlaybackSettlementError("unknown playback stream") from error

    @staticmethod
    def _identity(response_id: str, stream_id: int) -> tuple[str, int]:
        if not isinstance(response_id, str) or not response_id.strip():
            raise ValueError("response_id must be nonblank")
        if type(stream_id) is not int or stream_id < 0:
            raise ValueError("stream_id must be a non-negative integer")
        return response_id, stream_id

    @staticmethod
    def _count(value: int, name: str) -> int:
        if type(value) is not int or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")
        return value
