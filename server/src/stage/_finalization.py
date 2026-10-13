"""Manager-owned chat/call finalization tasks and admission facts."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from src.utils.logger import get_logger


class InteractionFinalizing(RuntimeError):
    def __init__(self) -> None:
        super().__init__("INTERACTION_FINALIZING")


class FinalizationTasks:
    def __init__(self) -> None:
        self._tasks: dict[str, tuple[tuple[str, str], asyncio.Task]] = {}

    def require_idle(self, key: tuple[str, str]) -> None:
        if any(owner == key and not task.done() for owner, task in self._tasks.values()):
            raise InteractionFinalizing()

    def has_user(self, user_id: str) -> bool:
        return any(owner[0] == user_id and not task.done() for owner, task in self._tasks.values())

    def start(
        self, identity: str, owner: tuple[str, str], operation: Callable[[], Coroutine[Any, Any, Any]]
    ) -> asyncio.Task:
        existing = self._tasks.get(identity)
        if existing is not None:
            return existing[1]
        task = asyncio.create_task(operation(), name=f"stage-finalize-{identity}")
        self._tasks[identity] = (owner, task)
        task.add_done_callback(lambda done: self._discard(identity, done))
        return task

    def _discard(self, identity: str, task: asyncio.Task) -> None:
        if self._tasks.get(identity, (None, None))[1] is task:
            self._tasks.pop(identity)
        if not task.cancelled():
            error = task.exception()
            if error is not None:
                get_logger(__name__).error(
                    "Stage finalization failed interaction=%s type=%s", identity, type(error).__name__
                )

    async def close(self) -> None:
        while self._tasks:
            await asyncio.gather(*(task for _, task in tuple(self._tasks.values())), return_exceptions=True)


class CallFinalizationSink:
    def __init__(self, manager, ownership) -> None:
        self._manager = manager
        self._ownership = ownership

    async def emit(self, snapshot) -> None:
        self._manager._start_call_finalization(self._ownership, snapshot)
