from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Optional

from src.utils.logger import get_logger


ClockAction = Callable[[], Any]


@dataclass
class _IntervalAction:
    name: str
    interval_seconds: float
    action: ClockAction
    run_immediately: bool = False


@dataclass
class _DailyAction:
    name: str
    hour: int
    minute: int
    action: ClockAction


class WorldClock:
    """Generic world clock that runs registered background actions."""

    def __init__(self) -> None:
        self.logger = get_logger(__name__)
        self._interval_actions: Dict[str, _IntervalAction] = {}
        self._daily_actions: Dict[str, _DailyAction] = {}
        self._tasks: Dict[str, asyncio.Task] = {}
        self._stop_event: Optional[asyncio.Event] = None

    def register_interval_action(
        self,
        name: str,
        interval_seconds: float,
        action: ClockAction,
        *,
        run_immediately: bool = False,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError(f"Interval action {name} requires a positive interval.")
        self._interval_actions[name] = _IntervalAction(
            name=name,
            interval_seconds=interval_seconds,
            action=action,
            run_immediately=run_immediately,
        )
        if self.is_running:
            self._start_interval_action(self._interval_actions[name])

    def register_daily_action(
        self,
        name: str,
        hour: int,
        minute: int,
        action: ClockAction,
    ) -> None:
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ValueError(f"Daily action {name} has invalid time {hour}:{minute}.")
        self._daily_actions[name] = _DailyAction(name=name, hour=hour, minute=minute, action=action)
        if self.is_running:
            self._start_daily_action(self._daily_actions[name])

    @property
    def is_running(self) -> bool:
        return self._stop_event is not None and not self._stop_event.is_set()

    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event = asyncio.Event()
        for action in self._interval_actions.values():
            self._start_interval_action(action)
        for action in self._daily_actions.values():
            self._start_daily_action(action)

    async def stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        self._stop_event = None

    def _start_interval_action(self, action: _IntervalAction) -> None:
        task_key = f"interval:{action.name}"
        old_task = self._tasks.get(task_key)
        if old_task is not None and not old_task.done():
            self.logger.info(f"Cancelling existing task for interval action {action.name}.")
            old_task.cancel()
        self._tasks[task_key] = asyncio.create_task(self._run_interval_action(action))

    def _start_daily_action(self, action: _DailyAction) -> None:
        task_key = f"daily:{action.name}"
        old_task = self._tasks.get(task_key)
        if old_task is not None and not old_task.done():
            self.logger.info(f"Cancelling existing task for daily action {action.name}.")
            old_task.cancel()
        self._tasks[task_key] = asyncio.create_task(self._run_daily_action(action))

    async def _run_interval_action(self, action: _IntervalAction) -> None:
        if action.run_immediately:
            await self._run_action(action.name, action.action)

        while not self._is_stopped():
            try:
                await asyncio.wait_for(self._wait_stopped(), timeout=action.interval_seconds)
                break
            except asyncio.TimeoutError:
                await self._run_action(action.name, action.action)

    async def _run_daily_action(self, action: _DailyAction) -> None:
        while not self._is_stopped():
            wait_seconds = self._seconds_until_next_time(datetime.now(), action.hour, action.minute)
            try:
                await asyncio.wait_for(self._wait_stopped(), timeout=wait_seconds)
                break
            except asyncio.TimeoutError:
                await self._run_action(action.name, action.action)

    async def _run_action(self, name: str, action: ClockAction) -> None:
        try:
            if inspect.iscoroutinefunction(action):
                result = action()
            else:
                result = await asyncio.to_thread(action)
            if inspect.isawaitable(result):
                await result
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.logger.warning(f"World clock action {name} failed: {e}")

    async def _wait_stopped(self) -> None:
        if self._stop_event is None:
            await asyncio.Future()
        await self._stop_event.wait()

    def _is_stopped(self) -> bool:
        return self._stop_event is not None and self._stop_event.is_set()

    @staticmethod
    def _seconds_until_next_time(now: datetime, hour: int, minute: int) -> float:
        next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now >= next_run:
            next_run = next_run + timedelta(days=1)
        return max((next_run - now).total_seconds(), 1.0)
