"""同一交互的数据访问状态及异步操作的完成边界。"""

import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")


async def _complete(operation: Coroutine[Any, Any, T]) -> T:
    # 取消调用者不能中断数据库写入后的内存同步，也不能遗留后台创建任务。
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


class _Lifecycle:
    def __init__(self, lock: asyncio.Lock | None = None) -> None:
        self.lock = lock if lock is not None else asyncio.Lock()
        self.closed = False

    def check(self) -> None:
        if self.closed:
            raise RuntimeError("交互上下文已经释放")
