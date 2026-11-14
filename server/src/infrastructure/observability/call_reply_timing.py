"""按回复请求关联首包计时；只保存时间和标识，不保存音频或文本。"""

import asyncio
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone

from src.infrastructure.observability.call_latency import call_latency

_current: ContextVar["CallReplyTiming | None"] = ContextVar("call_reply_timing", default=None)
_tts_worker = ContextVar("call_tts_worker", default=None)


@contextmanager
def call_tts_scope(call_id, response_id):
    """将工作线程接收的进程时间点交回所属事件循环，保持调用隔离。"""
    loop = asyncio.get_running_loop()
    timing = _current.get()
    seen = set()

    def record(phase, monotonic_ns):
        if phase in seen:
            return
        seen.add(phase)
        wall = datetime.now(timezone.utc) + timedelta(seconds=(monotonic_ns - time.monotonic_ns()) / 1e9)
        call_latency(
            f"tts.{phase}",
            call_id,
            response_id=response_id,
            monotonic_ns=monotonic_ns,
            timestamp=wall.isoformat(timespec="milliseconds"),
            measurement="worker_monotonic_clock",
        )
        if timing is not None and phase != "finished":
            timing.mark(f"tts_{phase}", at=monotonic_ns / 1e9)

    def receive(phase, monotonic_ns):
        loop.call_soon_threadsafe(record, phase, monotonic_ns)

    token = _tts_worker.set(receive)
    call_latency("tts.requested", call_id, response_id=response_id)
    mark_reply_phase("tts_requested")
    try:
        yield
    finally:
        _tts_worker.reset(token)


def record_tts_worker_event(phase, monotonic_ns):
    """只传递时间点，不跨进程或线程传递通话正文。"""
    receiver = _tts_worker.get()
    if receiver is not None:
        receiver(phase, monotonic_ns)


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
        speech_end_basis="audio_ingress_estimate",
        generation_started_at=None,
        response_id=None,
        segment_index=None,
        v2_sink=None,
        clock=time.monotonic,
        wall_clock=lambda: datetime.now(timezone.utc),
    ):
        self._clock = clock
        self._anchor = clock()
        self._wall = wall_clock()
        self._sink = sink
        self._v2_sink = v2_sink
        self.call_id = call_id
        self._metadata = {
            "reply_request_id": request_id,
            "turn_seq": turn_seq,
            "speech_end_basis": speech_end_basis if speech_ended_at is not None else "unavailable",
            "model_response_id": response_id,
            "segment_index": segment_index,
        }
        self._marks = {}
        if recognized_at is not None:
            self._marks["recognized"] = recognized_at
        if generation_started_at is not None:
            self._marks["generation_started"] = generation_started_at
        self._done = False
        if speech_ended_at is not None:
            self._marks["speech_end"] = speech_ended_at
            if recognized_at is not None:
                self._record("endpointing", speech_ended_at, recognized_at)
        if recognized_at is not None:
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

    def mark(self, phase, *, status="success", at=None):
        if self._done or phase in self._marks:
            return
        now = self._clock() if at is None else at
        previous = {
            "retrieval_started": "recognized",
            "retrieval_finished": "retrieval_started",
            "generation_started": "retrieval_finished",
            "reply_generated": "generation_started",
            "reply_submitted": "reply_generated",
            "tts_requested": "reply_submitted",
            "tts_started": "tts_requested",
            "tts_synthesized": "tts_started",
            "tts_first_packet": "tts_synthesized",
        }
        names = {
            "retrieval_started": "scheduling",
            "retrieval_finished": "retrieval",
            "generation_started": "generation_queue",
            "reply_generated": "generation",
            "reply_submitted": "submission",
            "tts_requested": "dispatch_wait",
            "tts_started": "tts_queue",
            "tts_synthesized": "tts_synthesis",
            "tts_first_packet": "tts_delivery",
        }
        start = self._marks.get(previous[phase])
        self._marks[phase] = now
        if start is not None:
            self._record(names[phase], start, now, status)
        if phase == "tts_synthesized" and self._v2_sink is not None:
            submitted = self._marks.get("reply_submitted")
            if submitted is not None:
                self._v2_sink("tts", submitted, now)
        if phase == "tts_first_packet":
            # 保留既有首包指标，同时明确它包含排队，不冒充纯合成耗时。
            submitted = self._marks.get("reply_submitted")
            if submitted is not None:
                self._record("tts_first_packet", submitted, now, status)
            if "speech_end" in self._marks:
                self._record("total", self._marks["speech_end"], now)
            self.finish("completed")

    def delivered(self, delivery_id):
        self._first_delivery_mark("first_sent", delivery_id)

    def acknowledged(self, delivery_id):
        self._first_delivery_mark("first_ack", delivery_id)

    def _first_delivery_mark(self, phase, delivery_id):
        key = (phase, delivery_id)
        if key in self._marks:
            return
        now = self._clock()
        self._marks[key] = now
        if "speech_end" in self._marks:
            self._record(phase, self._marks["speech_end"], now, delivery_id=delivery_id)

    def invalidate(self, delivery_id, reason):
        now = self._clock()
        self._record("invalidated", now, now, "error", delivery_id=delivery_id, reason=reason)

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
