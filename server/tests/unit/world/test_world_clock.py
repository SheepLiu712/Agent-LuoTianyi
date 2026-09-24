"""通过注册、启停与 action 结果冻结时钟行为，不运行真实 world 业务。"""

import asyncio
import threading
from datetime import datetime
from types import SimpleNamespace

import pytest

import src.world.world_clock as clock_module
from src.world.world_clock import WorldClock


class ControlledTimer:
    """替换时钟模块使用的超时边界，由测试显式触发到期。"""

    def __init__(self):
        self.waits = asyncio.Queue()

    async def wait_for(self, awaitable, timeout):
        expired = asyncio.get_running_loop().create_future()
        self.waits.put_nowait((timeout, expired))
        try:
            await expired
            raise asyncio.TimeoutError
        finally:
            awaitable.close()

    async def next_wait(self):
        return await asyncio.wait_for(self.waits.get(), 1)


@pytest.fixture
def timer(monkeypatch):
    controlled = ControlledTimer()
    # 只替换模块的时间边界，不修改全局 asyncio 或测试自身的超时保护。
    proxy = SimpleNamespace(**{name: getattr(asyncio, name) for name in dir(asyncio)})
    proxy.wait_for = controlled.wait_for
    monkeypatch.setattr(clock_module, "asyncio", proxy)
    return controlled


@pytest.mark.asyncio
@pytest.mark.parametrize("immediate", [False, True])
async def test_interval_waits_between_runs_and_honors_immediate(timer, immediate):
    clock = WorldClock()
    calls = []

    async def action():
        calls.append("run")
        return len(calls)

    clock.register_interval_action("tick", 37, action, run_immediately=immediate)
    clock.start()
    clock.start()
    try:
        delay, expired = await timer.next_wait()
        assert delay == 37
        assert calls == (["run"] if immediate else [])
        expired.set_result(None)
        delay, _ = await timer.next_wait()
        assert delay == 37
        assert len(calls) == 1 + int(immediate)
        assert clock.last_results["tick"] == len(calls)
        assert timer.waits.empty()
    finally:
        await clock.stop()
    assert not clock.is_running
    await clock.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("now, expected", [
    (datetime(2026, 9, 6, 3, 59, 30), 30),
    (datetime(2026, 9, 6, 4, 0), 86400),
    (datetime(2026, 9, 6, 5, 0), 82800),
])
async def test_daily_uses_next_server_local_time(timer, monkeypatch, now, expected):
    local_time = [now]

    class LocalDateTime:
        @staticmethod
        def now():
            return local_time[0]

    monkeypatch.setattr(clock_module, "datetime", LocalDateTime)
    calls = []

    async def action():
        calls.append("daily")

    clock = WorldClock()
    clock.register_daily_action("daily", 4, 0, action)
    clock.start()
    try:
        delay, expired = await timer.next_wait()
        assert delay == expected
        assert calls == []
        local_time[0] = datetime(2026, 9, 7, 4, 0)
        expired.set_result(None)
        delay, _ = await timer.next_wait()
        assert calls == ["daily"]
        assert delay == 86400
    finally:
        await clock.stop()


@pytest.mark.asyncio
async def test_action_failure_does_not_stop_peer_or_next_cycle(timer):
    clock = WorldClock()
    attempts = []

    async def flaky():
        attempts.append("attempt")
        if len(attempts) == 1:
            raise ValueError("expected failure")
        return "recovered"

    async def peer():
        return "healthy"

    clock.register_interval_action("flaky", 11, flaky, run_immediately=True)
    clock.register_interval_action("peer", 13, peer, run_immediately=True)
    clock.start()
    try:
        waits = dict([await timer.next_wait(), await timer.next_wait()])
        assert clock.last_results == {"peer": "healthy"}
        waits[11].set_result(None)
        assert (await timer.next_wait())[0] == 11
        assert attempts == ["attempt", "attempt"]
        assert clock.last_results == {"peer": "healthy", "flaky": "recovered"}
    finally:
        await clock.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["interval", "daily"])
async def test_same_name_replaces_waiting_loop(timer, kind):
    clock = WorldClock()
    calls = []

    async def old():
        calls.append("old")

    async def new():
        calls.append("new")

    def register(action):
        if kind == "interval":
            clock.register_interval_action("same", 19, action)
        else:
            clock.register_daily_action("same", 4, 0, action)

    register(old)
    clock.start()
    try:
        _, old_expiry = await timer.next_wait()
        register(new)
        _, new_expiry = await timer.next_wait()
        assert old_expiry.cancelled()
        new_expiry.set_result(None)
        await timer.next_wait()
        assert calls == ["new"]
        assert timer.waits.empty()
    finally:
        await clock.stop()


@pytest.mark.asyncio
async def test_stop_waits_for_async_action_cleanup():
    clock = WorldClock()
    started, cleaned = asyncio.Event(), asyncio.Event()

    async def action():
        started.set()
        try:
            await asyncio.Future()
        finally:
            await asyncio.sleep(0)
            cleaned.set()

    clock.register_interval_action("owned", 60, action, run_immediately=True)
    clock.start()
    try:
        await asyncio.wait_for(started.wait(), 1)
    finally:
        await clock.stop()
    assert cleaned.is_set()
    assert not clock.is_running


@pytest.mark.asyncio
async def test_stop_reports_live_sync_work_and_can_retry():
    # 从 test_runtime_shutdown.py 迁入；用关闭结果代替私有 _tasks 断言。
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    calls = []

    def action():
        calls.append("run")
        started.set()
        release.wait(timeout=5)
        finished.set()

    clock = WorldClock()
    clock.stop_timeout_seconds = 0.02
    clock.register_interval_action("blocking", 60, action, run_immediately=True)
    clock.start()
    try:
        assert await asyncio.to_thread(started.wait, 1)
        with pytest.raises(RuntimeError, match="still stopping"):
            await clock.stop()
        assert not finished.is_set()
        assert not clock.is_running
        # 线程仍被阻塞时再次关闭，不能仅因协程被第二次取消就报告成功。
        with pytest.raises(RuntimeError, match="still stopping"):
            await clock.stop()
    finally:
        release.set()
        assert await asyncio.to_thread(finished.wait, 1)
        clock.stop_timeout_seconds = 1
        await clock.stop()
    assert finished.is_set()
    assert calls == ["run"]
    await clock.stop()
