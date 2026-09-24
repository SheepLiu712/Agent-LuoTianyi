"""关闭必须等待公开门面的在途工作，调用取消保留清理所有权。"""
import asyncio

import pytest

import src.domain.agent as d
from routing_support import Sink, completed, plan_and_context, request, settlement  # noqa: F401


@pytest.mark.parametrize("side", ["handle", "realize"])
async def test_shutdown_times_out_without_releasing_inflight_dependencies_then_retries(routed_runtime, side):
    started, release = asyncio.Event(), asyncio.Event()

    async def handle(req, plans):
        started.set()
        await release.wait()
        return settlement(req)

    async def realize(action, ctx, outputs):
        started.set()
        await release.wait()
        return completed(action)

    runtime, store = routed_runtime(handle, realize)
    runtime.shutdown_timeout_seconds = 0.01
    agent = runtime.get_agent()
    plan, context = plan_and_context()
    call = asyncio.create_task(agent.handle_stimulus(request(), Sink()) if side == "handle"
                               else agent.realize_action_plan(plan, context, Sink()))
    try:
        await asyncio.wait_for(started.wait(), 0.5)
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await runtime.shutdown()
            assert store.close_calls == 0
            assert not call.done()
            rejection = await agent.handle_stimulus(request(), Sink())
            assert rejection.error_code is d.HandlingErrorCode.DEPENDENCY_UNAVAILABLE
        release.set()
        await call
        runtime.shutdown_timeout_seconds = 1
        await runtime.shutdown()
        await runtime.shutdown()
        assert store.close_calls == 1
    finally:
        release.set()
        await call


async def test_task_cancellation_propagates_only_after_handler_cleanup(routed_runtime):
    entered, cleaning, release_cleanup = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def handle(req, plans):
        try:
            entered.set()
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release_cleanup.wait()

    runtime, store = routed_runtime(handle=handle)
    call = asyncio.create_task(runtime.get_agent().handle_stimulus(request(), Sink()))
    try:
        await asyncio.wait_for(entered.wait(), 0.5)
        call.cancel()
        await asyncio.wait_for(cleaning.wait(), 0.5)
        runtime.shutdown_timeout_seconds = 0.01
        with pytest.raises(RuntimeError):
            await runtime.shutdown()
        assert store.close_calls == 0
        assert not call.done()
        release_cleanup.set()
        with pytest.raises(asyncio.CancelledError):
            await call
        runtime.shutdown_timeout_seconds = 1
        await runtime.shutdown()
        assert store.close_calls == 1
    finally:
        release_cleanup.set()
        if not call.done():
            call.cancel()
        await asyncio.gather(call, return_exceptions=True)

async def test_repeated_shutdown_keeps_cancelled_call_owned_sync_cleanup(routed_runtime):
    import threading
    from src.utils.asyncio_helpers import run_sync_owned

    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def work():
        started.set()
        try:
            release.wait(5)
        finally:
            finished.set()

    async def handle(req, plans):
        await run_sync_owned(work)
        return settlement(req)

    runtime, store = routed_runtime(handle=handle)
    runtime.shutdown_timeout_seconds = 0.01
    call = asyncio.create_task(runtime.get_agent().handle_stimulus(request(), Sink()))
    try:
        assert await asyncio.to_thread(started.wait, 0.5), "registered handler did not start sync work"
        call.cancel()
        await asyncio.sleep(0)
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await runtime.shutdown()
            assert not finished.is_set()
            assert not call.done()
            assert store.close_calls == 0
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await call
        assert await asyncio.to_thread(finished.wait, 1)
        runtime.shutdown_timeout_seconds = 1
        await runtime.shutdown()
        assert store.close_calls == 1
    finally:
        release.set()
        await asyncio.gather(call, return_exceptions=True)


async def test_repeated_caller_cancellation_cannot_release_sync_dependencies(routed_runtime):
    import threading
    from src.utils.asyncio_helpers import run_sync_owned

    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def work():
        started.set()
        try:
            release.wait(5)
        finally:
            finished.set()

    async def handle(req, plans):
        await run_sync_owned(work)
        return settlement(req)

    runtime, store = routed_runtime(handle=handle)
    runtime.shutdown_timeout_seconds = 0.05
    call = asyncio.create_task(runtime.get_agent().handle_stimulus(request(), Sink()))
    try:
        assert await asyncio.to_thread(started.wait, 0.5)
        call.cancel()
        # 一个事件循环轮次将首次取消送入 run_sync_owned 的清理等待。
        await asyncio.sleep(0)
        call.cancel()
        await asyncio.sleep(0)
        with pytest.raises(RuntimeError):
            await runtime.shutdown()
        assert store.close_calls == 0
        assert not finished.is_set()
        assert not call.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await call
        assert await asyncio.to_thread(finished.wait, 1)
        runtime.shutdown_timeout_seconds = 1
        await runtime.shutdown()
        assert store.close_calls == 1
    finally:
        release.set()
        await asyncio.gather(call, return_exceptions=True)
