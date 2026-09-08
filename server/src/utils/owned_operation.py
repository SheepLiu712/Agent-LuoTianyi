"""在调用者取消时，仍完成已经开始的资源生命周期变更。"""
import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")


async def complete_owned(operation: Coroutine[Any, Any, T]) -> T:
    """执行 operation 并返回其结果；调用者取消时先等待操作结束，再传播 CancelledError。"""
    task = asyncio.create_task(operation)
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            break
    if cancelled:
        if not task.cancelled():
            task.exception()
        raise asyncio.CancelledError
    return task.result()
