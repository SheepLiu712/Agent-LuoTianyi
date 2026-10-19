"""Manager-owned chat/call finalization tasks and admission facts."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from src.utils.logger import get_logger


class InteractionFinalizing(RuntimeError):
    def __init__(self) -> None:
        super().__init__("INTERACTION_FINALIZING")


@dataclass(slots=True)
class _InteractionTasks:
    owner: tuple[str, str]
    termination: asyncio.Task | None = None
    finalization: asyncio.Task | None = None


class FinalizationTasks:
    def __init__(self) -> None:
        self._tasks: dict[str, _InteractionTasks] = {}

    def require_idle(self, key: tuple[str, str]) -> None:
        if any(entry.owner == key and self._is_busy(entry) for entry in self._tasks.values()):
            raise InteractionFinalizing()

    def has_user(self, user_id: str) -> bool:
        return any(entry.owner[0] == user_id and self._is_busy(entry) for entry in self._tasks.values())

    def start_termination(
        self, identity: str, owner: tuple[str, str], operation: Callable[[], Coroutine[Any, Any, Any]]
    ) -> asyncio.Task:
        entry = self._entry(identity, owner)
        if entry.termination is not None:
            return entry.termination
        task = asyncio.create_task(operation(), name=f"stage-terminate-{identity}")
        entry.termination = task
        task.add_done_callback(lambda done: self._completed(identity, "termination", done))
        return task

    def start(
        self, identity: str, owner: tuple[str, str], operation: Callable[[], Coroutine[Any, Any, Any]]
    ) -> asyncio.Task:
        entry = self._entry(identity, owner)
        if entry.finalization is not None:
            return entry.finalization
        task = asyncio.create_task(operation(), name=f"stage-finalize-{identity}")
        entry.finalization = task
        task.add_done_callback(lambda done: self._completed(identity, "finalization", done))
        return task

    def _entry(self, identity: str, owner: tuple[str, str]) -> _InteractionTasks:
        entry = self._tasks.get(identity)
        if entry is None:
            entry = _InteractionTasks(owner)
            self._tasks[identity] = entry
        elif entry.owner != owner:
            raise RuntimeError("interaction task owner changed")
        return entry

    def _completed(self, identity: str, phase: str, task: asyncio.Task) -> None:
        entry = self._tasks.get(identity)
        if entry is None or getattr(entry, phase) is not task:
            return
        if not task.cancelled():
            error = task.exception()
            if error is not None:
                get_logger(__name__).error(
                    "Stage %s failed interaction=%s type=%s", phase, identity, type(error).__name__
                )
        # Stage 自身保留幂等终止句柄；Manager 只保留仍在执行的任务。
        if not self._is_busy(entry):
            self._tasks.pop(identity, None)

    @staticmethod
    def _is_busy(entry: _InteractionTasks) -> bool:
        return any(task is not None and not task.done() for task in (entry.termination, entry.finalization))

    async def close(self) -> None:
        while self._tasks:
            tasks = tuple(
                task
                for entry in self._tasks.values()
                for task in (entry.termination, entry.finalization)
                if task is not None
            )
            if not tasks:
                return
            await asyncio.gather(*tasks, return_exceptions=True)
            for identity, entry in tuple(self._tasks.items()):
                if entry.finalization is None and entry.termination is not None and entry.termination.done():
                    self._tasks.pop(identity, None)
