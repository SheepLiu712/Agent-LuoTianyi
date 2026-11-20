"""Run independent model calls together, owning their cancellation and cleanup."""

import asyncio

from src.utils.owned_operation import complete_owned


async def parallel_results(*operations, cancellation):
    tasks = [asyncio.create_task(operation) for operation in operations]
    group = asyncio.gather(*tasks)
    group.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    try:
        return await asyncio.shield(group)
    finally:
        cancelled = [task for task in tasks if not task.done() and task.cancel()]
        await complete_owned(_drain(tasks, cancelled, cancellation))


async def _drain(tasks, cancelled, cancellation):
    await asyncio.gather(*tasks, return_exceptions=True)
    for task in cancelled:
        if not task.cancelled() and (error := task.exception()) is not None:
            cancellation.record_cleanup_error(type(error).__name__)
