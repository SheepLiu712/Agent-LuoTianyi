"""Parent-owned TTS telemetry, including cancelled requests still running in the worker."""

import json
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from queue import Empty
from uuid import uuid4

from src.infrastructure.observability import get_observability_service
from src.utils.logger import get_logger

_current = ContextVar("tts_request_metrics", default=None)
_reference = ContextVar("tts_action_reference", default=None)
_lock = threading.RLock()
_requests = {}


def _safe(function, *args):
    try:
        function(*args)
    except Exception as error:
        get_logger(__name__).warning("TTS metric persistence failed type=%s", type(error).__name__)


@contextmanager
def tts_action_scope(action_id):
    token = _reference.set(action_id)
    try:
        yield
    finally:
        _reference.reset(token)


@contextmanager
def tts_request(invocation):
    request = TTSRequest(invocation)
    token = _current.set(request)
    try:
        yield request
    except BaseException as error:
        request.finish(
            "cancelled"
            if type(error).__name__ in {"CancelledError", "GeneratorExit", "TTSStreamCancelled"}
            else (
                "empty"
                if type(error).__name__ == "EmptySpeechError"
                else "timeout" if isinstance(error, TimeoutError) else "error"
            )
        )
        raise
    else:
        request.finish("success" if "returned" in request.marks else "empty")
    finally:
        _current.reset(token)


class TTSRequest:
    def __init__(self, invocation):
        self.store = get_observability_service()
        self.id = uuid4().hex
        self.worker = None
        self.status = "pending"
        self.marks = {"requested": time.monotonic()}
        self.row = {
            "request_id": self.id,
            "requested_at": datetime.now(timezone.utc).isoformat(),
            "user_id": invocation.user_id,
            "character_id": invocation.character_id,
            "interaction_id": invocation.interaction_id,
        }
        self.reference = _reference.get()
        if self.store is not None:
            with _lock:
                _requests[self.id] = self
                self.persist()

    def mark(self, phase, at=None, worker=None):
        if self.store is None:
            return
        with _lock:
            if phase in self.marks:
                return
            snapshot_queues(self.worker)
            if worker is not None:
                self.worker = worker
            self.marks.setdefault(phase, time.monotonic() if at is None else at)
            self.persist()
            snapshot_queues(self.worker)
            self._release()

    def finish(self, status):
        with _lock:
            self.status = status
            self.mark("consumer_finished")

    def _release(self):
        if "consumer_finished" in self.marks and ("submitted" not in self.marks or "worker_finished" in self.marks):
            _requests.pop(self.id, None)

    def persist(self):
        if self.store is None:
            return

        def duration(start, end):
            if start not in self.marks or end not in self.marks:
                return None
            return max(0, self.marks[end] - self.marks[start]) * 1000

        _safe(
            self.store.record_tts_request,
            {
                **self.row,
                "worker_id": self.worker,
                "status": self.status,
                "queue_ms": duration("requested", "worker_started"),
                "synthesis_ms": duration("worker_started", "first_audio"),
                "first_audio_ms": duration("requested", "first_audio"),
                "returned_ms": duration("requested", "returned"),
                "metadata_json": json.dumps({"action_id": self.reference, "marks": self.marks}),
            },
        )


def mark_tts(phase, *, worker=None):
    request = _current.get()
    if request is not None:
        request.mark(phase, worker=worker)


def tts_request_id():
    request = _current.get()
    return request.id if request is not None and request.store is not None else None


def snapshot_queues(worker=None):
    now = time.monotonic()
    bucket = datetime.fromtimestamp(int(time.time()) // 300 * 300, timezone.utc).isoformat()
    workers = {r.worker for r in _requests.values() if r.worker is not None}
    for identity in workers:
        if worker is not None and identity != worker:
            continue
        requests = [r for r in _requests.values() if r.worker == identity]
        waiting = [
            r
            for r in requests
            if "worker_started" not in r.marks
            and (r.status == "pending" or "submitted" in r.marks)
            and "worker_finished" not in r.marks
        ]
        running = [r for r in requests if "worker_started" in r.marks and "worker_finished" not in r.marks]
        oldest = max((now - r.marks["requested"] for r in waiting), default=0) * 1000
        _safe(requests[0].store.record_tts_queue, bucket, identity, len(waiting), len(running), oldest)


def worker_event(request_id, phase, monotonic_ns):
    with _lock:
        request = _requests.get(request_id)
        if request is not None:
            request.mark(phase, monotonic_ns / 1e9)


def drain_worker_metrics(queue, worker, is_alive=None):
    last_sample = 0
    while True:
        try:
            event = queue.get(timeout=1)
            if event is None:
                break
            worker_event(*event)
        except Empty:
            if is_alive is not None and not is_alive():
                break
        except (EOFError, OSError, ValueError):
            break
        if time.monotonic() - last_sample >= 10:
            with _lock:
                snapshot_queues(worker)
            last_sample = time.monotonic()
    with _lock:
        for request in list(_requests.values()):
            if request.worker == worker:
                request.mark("worker_finished")
                if request.status == "pending":
                    request.finish("worker_lost")


def emit_worker_metric(queue, message, phase):
    if queue is not None and message.get("telemetry_id"):
        try:
            queue.put((message["telemetry_id"], phase, time.monotonic_ns()))
        except (OSError, ValueError):
            pass
