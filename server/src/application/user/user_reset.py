"""Complete user-owned data reset without changing account credentials."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable, Protocol

from src.utils.owned_operation import complete_owned


class UserResetFencePort(Protocol):
    async def begin_user_data_reset(self, user_id: str) -> object: ...

    async def stop_user_interactions(self, user_id: str) -> int: ...

    async def wait_user_settlements(self, user_id: str) -> None: ...

    async def end_user_data_reset(self, user_id: str, token: object) -> None: ...


@dataclass(frozen=True)
class UserResetStep:
    name: str
    success: bool
    deleted_count: int = 0
    error: str | None = None


@dataclass(frozen=True)
class UserResetReport:
    user_id: str
    steps: tuple[UserResetStep, ...]

    @property
    def success(self) -> bool:
        return all(step.success for step in self.steps)

    @property
    def failed_steps(self) -> tuple[str, ...]:
        return tuple(step.name for step in self.steps if not step.success)


class UserResetService:
    """Fence writes, drain interactions, then retry-safely delete user-owned data."""

    def __init__(
        self,
        *,
        interactions: UserResetFencePort,
        conversation_service,
        memory_store,
        user_store,
        vector_store,
        redis_buffer,
        media_store,
        call_sessions,
        call_maintenance_batches,
    ) -> None:
        self._interactions = interactions
        self._conversation_service = conversation_service
        self._memory_store = memory_store
        self._user_store = user_store
        self._vector_store = vector_store
        self._redis = redis_buffer
        self._media_store = media_store
        self._call_sessions = call_sessions
        self._call_maintenance_batches = call_maintenance_batches

    async def reset(self, user_id: str) -> UserResetReport:
        return await complete_owned(self._reset_owned(user_id))

    async def _reset_owned(self, user_id: str) -> UserResetReport:
        token = await self._interactions.begin_user_data_reset(user_id)
        try:
            lifecycle = await self._quiesce(user_id)
            if not lifecycle.success:
                return UserResetReport(user_id, (lifecycle,))
            steps = [lifecycle]
            steps.extend(
                [
                    await self._count("vectors", self._delete_vectors, user_id),
                    await self._count("canonical_memory", self._memory_store.delete_user_memory_records, user_id),
                    await self._count(
                        "call_maintenance_batches", self._call_maintenance_batches.delete_by_user, user_id
                    ),
                    await self._count("call_sessions", self._call_sessions.delete_by_user, user_id),
                    await self._count("conversations", self._conversation_service.reset_user_conversations, user_id),
                    await self._count("profile", self._user_store.reset_user_profile, user_id),
                    await self._void("cache", self._redis.clear_user, user_id),
                    await self._media(user_id),
                ]
            )
            return UserResetReport(user_id, tuple(steps))
        finally:
            await self._interactions.end_user_data_reset(user_id, token)

    async def _quiesce(self, user_id: str) -> UserResetStep:
        try:
            stopped = await self._interactions.stop_user_interactions(user_id)
            await self._interactions.wait_user_settlements(user_id)
            return UserResetStep("interactions", True, stopped)
        except Exception as error:
            return UserResetStep("interactions", False, error=type(error).__name__)

    def _delete_vectors(self, user_id: str) -> int:
        operation = getattr(self._vector_store, "delete_user_records_strict", None)
        if operation is None:
            raise RuntimeError("strict vector deletion is unavailable")
        return operation(user_id)

    @staticmethod
    async def _count(name: str, operation: Callable[[str], int], user_id: str) -> UserResetStep:
        try:
            count = await complete_owned(asyncio.to_thread(operation, user_id))
        except Exception as error:
            return UserResetStep(name, False, error=type(error).__name__)
        return UserResetStep(name, True, count)

    @staticmethod
    async def _void(name: str, operation: Callable[[str], None], user_id: str) -> UserResetStep:
        try:
            await complete_owned(asyncio.to_thread(operation, user_id))
        except Exception as error:
            return UserResetStep(name, False, error=type(error).__name__)
        return UserResetStep(name, True)

    async def _media(self, user_id: str) -> UserResetStep:
        try:
            report = await complete_owned(asyncio.to_thread(self._media_store.delete_owned_by, owner_user_id=user_id))
        except Exception as error:
            return UserResetStep("media", False, error=type(error).__name__)
        if report.failures:
            return UserResetStep("media", False, report.deleted_count, "MEDIA_DELETE_PARTIAL")
        return UserResetStep("media", True, report.deleted_count)
