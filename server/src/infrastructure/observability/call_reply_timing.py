"""按回复请求关联首包计时；只保存时间和标识，不保存音频或文本。"""

import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone

_current: ContextVar["CallReplyTiming | None"] = ContextVar("call_reply_timing", default=None)


@contextmanager
def reply_timing_scope(timing):
    token = _current.set(timing)
    try:
        yield
    finally:
        _current.reset(token)


def mark_reply_phase(phase: str, *, status: str = "success") -> None:
    timing = _current.get()
    if timing is not None:
        timing.mark(phase, status=status)


def record_retrieval_details(details):
    timing = _current.get()
    if timing is not None:
        timing.record_retrieval_details(details)


class CallReplyTiming:
    """一轮回复的阶段时钟；首次首包后冻结，重复分句不重复统计。"""

    def __init__(
        self,
        *,
        call_id,
        request_id,
        turn_seq,
        recognized_at,
        speech_ended_at,
        sink,
        clock=time.monotonic,
        wall_clock=lambda: datetime.now(timezone.utc),
    ):
        self._clock = clock
        self._anchor = clock()
        self._wall = wall_clock()
        self._sink = sink
        self.call_id = call_id
        self._metadata = {
            "reply_request_id": request_id,
            "turn_seq": turn_seq,
            "speech_end_basis": "audio_ingress_estimate" if speech_ended_at is not None else "unavailable",
        }
        self._marks = {"recognized": recognized_at}
        self._done = False
        if speech_ended_at is not None:
            self._marks["speech_end"] = speech_ended_at
            self._record("endpointing", speech_ended_at, recognized_at)
        self._record("recognized", recognized_at, recognized_at)

    def _record(self, phase, start, end, status="success", **metadata):
        if self._sink is None:
            return
        self._sink(
            call_id=self.call_id,
            phase=phase,
            start_ts=(self._wall + timedelta(seconds=start - self._anchor)).isoformat(timespec="milliseconds"),
            end_ts=(self._wall + timedelta(seconds=end - self._anchor)).isoformat(timespec="milliseconds"),
            duration_ms=max(0, (end - start) * 1000),
            status=status,
            metadata={**self._metadata, **metadata},
        )

    def mark(self, phase, *, status="success"):
        if self._done or phase in self._marks:
            return
        now = self._clock()
        previous = {
            "retrieval_started": "recognized",
            "retrieval_finished": "retrieval_started",
            "generation_started": "retrieval_finished",
            "reply_generated": "generation_started",
            "reply_submitted": "reply_generated",
            "tts_first_packet": "reply_submitted",
        }
        names = {
            "retrieval_started": "scheduling",
            "retrieval_finished": "retrieval",
            "generation_started": "generation_queue",
            "reply_generated": "generation",
            "reply_submitted": "submission",
            "tts_first_packet": "tts_first_packet",
        }
        start = self._marks.get(previous[phase])
        self._marks[phase] = now
        if start is not None:
            self._record(names[phase], start, now, status)
        if phase == "tts_first_packet":
            if "speech_end" in self._marks:
                self._record("total", self._marks["speech_end"], now)
            self.finish("completed")

    def record_retrieval_details(self, details):
        if self._done:
            return
        end = self._clock()
        for name, row in details.items():
            self._record(
                "retrieval." + name,
                end - row["duration_ms"] / 1000,
                end,
                row["status"],
                operation_count=row["count"],
                aggregated=True,
            )

    def finish(self, outcome):
        if self._done:
            return
        self._done = True
        now = self._clock()
        self._record("terminal", now, now, "success" if outcome == "completed" else "error", outcome=outcome)
