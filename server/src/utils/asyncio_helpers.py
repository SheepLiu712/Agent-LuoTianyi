from __future__ import annotations

import asyncio
from concurrent.futures import Executor
from functools import partial
from typing import Any, Callable, Iterable


DEFAULT_OWNED_TASK_STOP_TIMEOUT_SECONDS = 30.0


async def run_sync_owned(
    call: Callable[..., Any],
    *args: Any,
    executor: Executor | None = None,
    **kwargs: Any,
) -> Any:
    """Run owned sync work without abandoning it when the caller is cancelled."""
    loop = asyncio.get_running_loop()
    bound_call = partial(call, *args, **kwargs)
    future = loop.run_in_executor(executor, bound_call)
    try:
        return await asyncio.shield(future)
    except asyncio.CancelledError:
        await asyncio.shield(asyncio.gather(future, return_exceptions=True))
        raise


def cancel_task_once(task: asyncio.Task) -> None:
    """Request cancellation without interrupting an in-progress owned cleanup wait."""
    if task.done() or task.cancelling():
        return
    task.cancel()


async def wait_for_owned_tasks(
    tasks: Iterable[asyncio.Task],
    *,
    timeout_seconds: float = DEFAULT_OWNED_TASK_STOP_TIMEOUT_SECONDS,
) -> tuple[set[asyncio.Task], set[asyncio.Task]]:
    """Wait for owned tasks without cancelling or detaching them on timeout."""
    owned_tasks = set(tasks)
    if not owned_tasks:
        return set(), set()
    timeout = max(0.001, float(timeout_seconds))
    return await asyncio.wait(owned_tasks, timeout=timeout)
