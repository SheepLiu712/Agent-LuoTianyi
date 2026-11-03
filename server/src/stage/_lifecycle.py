"""Chat、Call 共用的任务所有权与取消规则，不执行交互业务。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from src.domain.stage.lifecycle import (
    ManagedStage,
    StageEndReason,
    StageInitializationFailed,
    StageInitializationOwner,
    StageLifecycleState,
    StageStartAborted,
    StageTerminationOwner,
    StageTerminationResult,
)


class StageLifetime:
    def __init__(
        self,
        stage: ManagedStage,
        *,
        own_initialization: StageInitializationOwner | None = None,
        own_termination: StageTerminationOwner | None = None,
        ready: bool = False,
    ):
        self.stage = stage
        self.state = StageLifecycleState.RUNNING if ready else StageLifecycleState.PREPARING
        self.interaction_ended = False
        self.initialization: asyncio.Task[None] | None = None
        self.termination: asyncio.Task[StageTerminationResult] | None = None
        self.reason: StageEndReason | None = None
        self._own_initialization = own_initialization
        self._own_termination = own_termination

    def initialize(self, operation: Callable[[], Awaitable[None]]) -> None:
        if self.initialization is None:
            self.initialization = self._spawn(self._own_initialization, lambda: self._initialize(operation))

    def _spawn(self, owner, operation):
        task = owner(self.stage, operation) if owner else asyncio.create_task(operation())
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        return task

    async def _initialize(self, operation: Callable[[], Awaitable[None]]) -> None:
        try:
            await operation()
            if self.termination is not None:
                raise StageStartAborted("stage ended during initialization")
            self.state = StageLifecycleState.RUNNING
        except BaseException as error:
            if self.termination is not None:
                if self.reason is StageEndReason.INITIALIZATION_FAILED:
                    raise StageInitializationFailed("stage initialization failed") from error
                raise StageStartAborted("stage ended during initialization") from error
            self.stage.begin_termination(StageEndReason.INITIALIZATION_FAILED)
            raise StageInitializationFailed("stage initialization failed") from error

    async def start(self) -> None:
        if self.initialization is not None:
            await asyncio.shield(self.initialization)

    def begin(self, reason: StageEndReason, operation: Callable[[], Awaitable[StageTerminationResult]]) -> None:
        if not isinstance(reason, StageEndReason):
            raise TypeError("reason must be StageEndReason")
        if self.termination is None:
            self.reason = reason
            self.state = StageLifecycleState.TERMINATING
            self.termination = self._spawn(self._own_termination, lambda: self._finish(operation))

    async def _finish(self, operation: Callable[[], Awaitable[StageTerminationResult]]) -> StageTerminationResult:
        result = await operation()
        if result.resources_released:
            self.state = StageLifecycleState.TERMINATED
        return result

    async def stop_initialization(self) -> None:
        task = self.initialization
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
