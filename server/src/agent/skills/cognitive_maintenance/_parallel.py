"""Run independent model calls together, owning their cancellation and cleanup."""

import asyncio

from src.utils.owned_operation import complete_owned


async def parallel_results(*operations):
    tasks = [asyncio.create_task(operation) for operation in operations]
    try:
        return await asyncio.shield(asyncio.gather(*tasks))
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await complete_owned(_drain(tasks))


async def _drain(tasks):
    await asyncio.gather(*tasks, return_exceptions=True)
