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
        user_reset_fence=None,
        call_owner=None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._consumer = consumer
        self._resources = resources
        self._timeout = timeout_seconds
        self._user_reset_fence = user_reset_fence
        self._call_owner = call_owner
        self._tasks: dict[UUID, asyncio.Task[None]] = {}
        self._task_users: dict[UUID, str] = {}

    async def emit(self, snapshot: CallFinalSnapshot) -> None:
        call_id = snapshot.terminal.call_id
        user_id = self._resolve_user_id(call_id)
        if self._user_reset_fence is not None:
            try:
                await self._user_reset_fence.require_admission(user_id)
            except Exception:
                self._release_rejected(call_id)
                raise
        task = self._tasks.get(call_id)
        if task is not None and not task.done():
            return
        task = asyncio.create_task(self._run(snapshot), name=f"call-settlement-{call_id}")
        self._tasks[call_id] = task
        if user_id is not None:
            self._task_users[call_id] = user_id
        if self._user_reset_fence is not None and user_id is not None:
            try:
                await self._user_reset_fence.track(user_id, task)
            except Exception:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                self._tasks.pop(call_id, None)
                self._task_users.pop(call_id, None)
                self._release_rejected(call_id)
                raise
        task.add_done_callback(lambda done, key=call_id: self._discard(key, done))

    def _resolve_user_id(self, call_id: UUID) -> str | None:
        if self._call_owner is None:
            if self._user_reset_fence is not None:
                raise RuntimeError("call owner resolver is required with reset fencing")
            return None
        record = self._call_owner(call_id)
        if record is None or not isinstance(record.user_id, str) or not record.user_id:
            raise RuntimeError("call owner is unavailable")
        return record.user_id

    def _release_rejected(self, call_id: UUID) -> None:
        release_maintenance = getattr(self._resources, "release_call_maintenance", None)
        if release_maintenance is not None:
            release_maintenance(call_id)
        self._resources.release_call_resources(call_id)

    async def close(self) -> None:
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks.values()), return_exceptions=True)

    async def wait_user(self, user_id: str) -> None:
        tasks = tuple(task for call_id, task in self._tasks.items() if self._task_users.get(call_id) == user_id)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _run(self, snapshot: CallFinalSnapshot) -> None:
        call_id = snapshot.terminal.call_id
        operation = asyncio.create_task(self._consumer.settle(snapshot), name=f"call-settlement-consumer-{call_id}")
        try:
            await asyncio.wait_for(asyncio.shield(operation), timeout=self._timeout)
        except TimeoutError:
            get_logger(__name__).warning("Call settlement timed out call_id=%s", call_id)
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)
        except Exception as error:  # noqa: BLE001 - terminal cleanup must run after any consumer failure
            get_logger(__name__).error("Call settlement failed call_id=%s type=%s", call_id, type(error).__name__)
        finally:
            if not operation.done():
                operation.cancel()
                await asyncio.gather(operation, return_exceptions=True)
            self._resources.release_call_resources(call_id)

    def _discard(self, call_id: UUID, task: asyncio.Task[None]) -> None:
        if self._tasks.get(call_id) is task:
            self._tasks.pop(call_id, None)
            self._task_users.pop(call_id, None)
