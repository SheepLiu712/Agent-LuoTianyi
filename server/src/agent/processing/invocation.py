"""处理器任务的调用、取消及清理等待。"""
import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, TypeVar

import src.domain.agent as d
from .plan_emitter import _DeliveryCancelled

if TYPE_CHECKING:
    from src.agent.facade import Agent

_Result = TypeVar("_Result")


class _HandlerNotStarted(_DeliveryCancelled):
    """处理器任务调度后、业务调用前已取消。"""


async def call_handler(
    agent: "Agent", call: Callable[[], Awaitable[_Result]],
    cancellation: d.CancellationToken, call_id: str, interaction_id: str,
) -> _Result:
    """调用处理器，并在任务取消时等待处理器完成清理。

    参数：
        agent (Agent)：提供清理异常的错误分类和日志记录。
        call (Callable[[], Awaitable[_Result]])：无参数的处理器调用函数，
            返回可等待对象，其结果类型由具体处理器决定。
        cancellation (CancellationToken)：开始调用前检查的协作取消令牌。
        call_id (str)：本次请求或执行的标识，用于关联异常日志。
        interaction_id (str)：当前交互标识，用于关联异常日志。

    返回：
        _Result：处理器正常返回的结果。

    异常：
        _HandlerNotStarted：处理器开始前，协作取消令牌已被取消。
        asyncio.CancelledError：调用任务被取消；先取消处理器任务并等待其
            清理结束，再传播取消。等待期间的重复取消不会再次打断处理器清理。
        处理器正常调用期间抛出的其他异常直接传播；取消清理中的异常记录日志。
    """
    # 当前调用拥有处理器任务；调用方重复取消不能再次取消其正在进行的清理。
    async def run():
        if cancellation.is_cancelled:
            raise _HandlerNotStarted()
        return await call()

    worker = asyncio.create_task(run())
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        worker.cancel()
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not worker.cancelled():
            cleanup_error = worker.exception()
            if cleanup_error is not None:
                agent._record_exception(
                    call_id, interaction_id, agent._error_code(cleanup_error, d.ExecutionErrorCode), cleanup_error
                )
        raise

