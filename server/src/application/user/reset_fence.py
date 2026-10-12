"""Per-user reset admission and owned-operation registry."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UserResetToken:
    user_id: str
    generation: int


class UserResetFence:
    """Block new per-user work while allowing already-owned tasks to drain."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._resetting: dict[str, UserResetToken] = {}
        self._operations: dict[str, set[asyncio.Task]] = {}
        self._user_generations: dict[str, int] = {}
        self._generation = 0

    async def begin(self, user_id: str) -> UserResetToken:
        async with self._lock:
            if user_id in self._resetting:
                raise RuntimeError("USER_DATA_RESET_IN_PROGRESS")
            self._generation += 1
            token = UserResetToken(user_id, self._generation)
            self._resetting[user_id] = token
            self._user_generations[user_id] = token.generation
            return token

    async def end(self, user_id: str, token: UserResetToken) -> None:
        async with self._lock:
            if self._resetting.get(user_id) != token:
                raise RuntimeError("USER_DATA_RESET_TOKEN_MISMATCH")
            self._resetting.pop(user_id)

    async def require_admission(self, user_id: str) -> None:
        async with self._lock:
            if user_id in self._resetting:
                raise RuntimeError("USER_DATA_RESET_IN_PROGRESS")

    async def track(self, user_id: str, task: asyncio.Task) -> None:
        async with self._lock:
            if user_id in self._resetting:
                raise RuntimeError("USER_DATA_RESET_IN_PROGRESS")
            tasks = self._operations.setdefault(user_id, set())
            tasks.add(task)
            task.add_done_callback(lambda done, owner=user_id: self._discard(owner, done))

    async def track_current(self, user_id: str) -> int:
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("USER_OPERATION_TASK_UNAVAILABLE")
        async with self._lock:
            if user_id in self._resetting:
                raise RuntimeError("USER_DATA_RESET_IN_PROGRESS")
            self._track_locked(user_id, task)
            return self._user_generations.get(user_id, 0)

    async def spawn(self, user_id: str, operation, *, name: str) -> tuple[asyncio.Task, int]:
        async with self._lock:
            if user_id in self._resetting:
                operation.close()
                raise RuntimeError("USER_DATA_RESET_IN_PROGRESS")
            generation = self._user_generations.get(user_id, 0)
            task = asyncio.create_task(operation, name=name)
            self._track_locked(user_id, task)
            return task, generation

    async def spawn_factory(self, user_id: str, factory, *, name: str) -> tuple[asyncio.Task, int]:
        async with self._lock:
            if user_id in self._resetting:
                raise RuntimeError("USER_DATA_RESET_IN_PROGRESS")
            generation = self._user_generations.get(user_id, 0)
            task = asyncio.create_task(factory(generation), name=name)
            self._track_locked(user_id, task)
            return task, generation

    async def require_generation(self, user_id: str, generation: int) -> None:
        async with self._lock:
            if user_id in self._resetting or self._user_generations.get(user_id, 0) != generation:
                raise RuntimeError("USER_DATA_RESET_INVALIDATED_OPERATION")

    async def wait(self, user_id: str) -> None:
        current = asyncio.current_task()
        while True:
            tasks = tuple(task for task in self._operations.get(user_id, ()) if task is not current and not task.done())
            if not tasks:
                return
            await asyncio.gather(*tasks, return_exceptions=True)

    def is_resetting(self, user_id: str) -> bool:
        return user_id in self._resetting

    def _discard(self, user_id: str, task: asyncio.Task) -> None:
        tasks = self._operations.get(user_id)
        if tasks is None:
            return
        tasks.discard(task)
        if not tasks:
            self._operations.pop(user_id, None)

    def _track_locked(self, user_id: str, task: asyncio.Task) -> None:
        tasks = self._operations.setdefault(user_id, set())
        tasks.add(task)
        task.add_done_callback(lambda done, owner=user_id: self._discard(owner, done))
