"""Live connection progress, with one slow-admission warning and no business cancellation."""

import asyncio
import time
from uuid import uuid4

from src.utils.logger import get_logger
from src.utils.task_diagnostics import task_snapshot

_SLOW_READY_SECONDS = 10.0


class ConnectionDiagnostics:
    def __init__(self, user_id: str) -> None:
        self.connection_id = uuid4().hex
        self.user_id = user_id
        self.phase = "created"
        self.started = self.phase_started = time.monotonic()
        self.stage = None
        self.previous_connection_id = None
        self.task = None
        self._warning: asyncio.TimerHandle | None = None

    def enter(self, phase: str) -> None:
        self.phase = phase
        self.phase_started = time.monotonic()
        self.task = asyncio.current_task()
        if self._warning is None:
            self._warning = asyncio.get_running_loop().call_later(_SLOW_READY_SECONDS, self._warn)

    def ready(self, future: asyncio.Future) -> None:
        if self.phase != "sending_ready":
            return
        self.enter("ready_send_failed" if future.cancelled() or future.exception() else "ready_sent")
        if self._warning is not None:
            self._warning.cancel()
        self.task = None

    def close(self) -> None:
        self.phase = "closed"
        self.phase_started = time.monotonic()
        self.task = None
        if self._warning is not None:
            self._warning.cancel()

    def snapshot(self) -> dict:
        now = time.monotonic()
        return {
            "connection_id": self.connection_id,
            "previous_connection_id": self.previous_connection_id,
            "phase": self.phase,
            "elapsed_ms": round((now - self.started) * 1000),
            "phase_elapsed_ms": round((now - self.phase_started) * 1000),
            "task": task_snapshot(self.task),
            "stage": self.stage.diagnostics() if self.stage is not None else None,
        }

    def _warn(self) -> None:
        get_logger(__name__).warning("Chat readiness delayed user_id=%s diagnostics=%s", self.user_id, self.snapshot())
