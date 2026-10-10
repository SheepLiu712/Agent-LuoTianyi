"""Bounded background handoff for immutable post-call settlement snapshots."""

from __future__ import annotations

import asyncio
from typing import Protocol
from uuid import UUID

from src.domain.call import CallFinalSnapshot
from src.utils.logger import get_logger


class CallSettlementConsumer(Protocol):
    async def settle(self, snapshot: CallFinalSnapshot) -> None:
        """Persist real summary/maintenance results or raise without claiming success."""


class CallResourceReleasePort(Protocol):
    def release_call_resources(self, call_id: UUID) -> bool: ...


class CallSettlementCoordinator:
    """Accept immutable snapshots quickly and bound all cleanup to fifteen seconds."""

    def __init__(
        self,
        *,
        consumer: CallSettlementConsumer,
        resources: CallResourceReleasePort,
        timeout_seconds: float = 15.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._consumer = consumer
        self._resources = resources
        self._timeout = timeout_seconds
        self._tasks: dict[UUID, asyncio.Task[None]] = {}

    async def emit(self, snapshot: CallFinalSnapshot) -> None:
        call_id = snapshot.terminal.call_id
        task = self._tasks.get(call_id)
        if task is not None and not task.done():
            return
        task = asyncio.create_task(self._run(snapshot), name=f"call-settlement-{call_id}")
        self._tasks[call_id] = task
        task.add_done_callback(lambda done, key=call_id: self._discard(key, done))

    async def close(self) -> None:
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks.values()), return_exceptions=True)

    async def _run(self, snapshot: CallFinalSnapshot) -> None:
        call_id = snapshot.terminal.call_id
        try:
            await asyncio.wait_for(self._consumer.settle(snapshot), timeout=self._timeout)
        except TimeoutError:
            get_logger(__name__).warning("Call settlement timed out call_id=%s", call_id)
        except Exception as error:  # noqa: BLE001 - terminal cleanup must run after any consumer failure
            get_logger(__name__).error("Call settlement failed call_id=%s type=%s", call_id, type(error).__name__)
        finally:
            self._resources.release_call_resources(call_id)

    def _discard(self, call_id: UUID, task: asyncio.Task[None]) -> None:
        if self._tasks.get(call_id) is task:
            self._tasks.pop(call_id, None)
