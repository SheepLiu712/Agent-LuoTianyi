"""Content-free reply phase clocks, scoped to a single handling attempt."""

import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone

from src.infrastructure.observability import get_observability_service
from src.infrastructure.observability.stage_timing import stage_timing
from src.utils.logger import get_logger

_current = ContextVar("chat_reply_metrics", default=None)


def record_duration(identity, name, start, end=None, status="success", **metadata):
    end = time.monotonic() if end is None else end
    store = get_observability_service()
    if store is None:
        return
    wall = datetime.now(timezone.utc)
    try:
        store.defer_metric_write(
            store.record_pipeline_span,
            trace_id=str(identity),
            span_name=name,
            start_ts=(wall - timedelta(seconds=max(0, time.monotonic() - start))).isoformat(),
            end_ts=(wall - timedelta(seconds=max(0, time.monotonic() - end))).isoformat(),
            duration_ms=max(0, end - start) * 1000,
            status=status,
            metadata=metadata,
        )
    except Exception as error:
        get_logger(__name__).warning("Reply timing persistence failed type=%s", type(error).__name__)


class ChatReplyTiming:
    def __init__(self, request_id, ready_at):
        self.identity = f"chat:{request_id}"
        self.ready_at = ready_at
        self.generated_at = self.llm_started = None
        self.delivered = False
        self.ended = False
        record_duration(self.identity, "chat.v2.wait", ready_at)

    def generation_started(self):
        if self.llm_started is None:
            self.llm_started = time.monotonic()

    def generated(self):
        if self.generated_at is None:
            self.generated_at = time.monotonic()
            if self.llm_started is not None:
                record_duration(self.identity, "chat.v2.generation", self.llm_started, self.generated_at)

    def delivery(self):
        if self.delivered:
            return
        self.delivered = True
        record_duration(self.identity, "chat.v2.total", self.ready_at)
        if self.generated_at is not None:
            record_duration(self.identity, "chat.v2.delivery", self.generated_at)
        self.finish("success")

    def finish(self, status):
        if not self.ended:
            self.ended = True
            record_duration(self.identity, "chat.v2.terminal", time.monotonic(), status=status)


@contextmanager
def chat_reply_scope(timing):
    token = _current.set(timing)
    try:
        yield
    finally:
        _current.reset(token)


def mark_chat_generation(phase):
    timing = _current.get()
    if timing is not None:
        (timing.generation_started if phase == "started" else timing.generated)()


@contextmanager
def chat_phase(name):
    timing = _current.get()
    if timing is None:
        yield
    else:
        with stage_timing(timing.identity, f"chat.v2.{name}"):
            yield
