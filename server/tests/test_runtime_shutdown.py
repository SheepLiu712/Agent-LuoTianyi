import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.chat_session.chat_pipeline.chat_stream import ChatStream
from src.chat_session.chat_session_manager import ChatSessionManager
from src.chat_session.chat_stream_manager import ChatStreamManager
from src.system.admin import admin_shell as admin_shell_module
from src.system.admin.admin_shell import AdminShell
from src.system.admin.runtime_supervisor import RuntimeSupervisor
from src.system.system_runtime import SystemRuntime
from src.utils.llm.client_llm_executor import ClientLLMExecutor


class FakeWebSocket:
    def __init__(self, failures=0):
        self.failures = failures
        self.close_calls = 0

    async def close(self):
        self.close_calls += 1
        if self.close_calls <= self.failures:
            raise RuntimeError("close failed")


@pytest.mark.asyncio
async def test_chat_stream_stop_awaits_workers_and_is_idempotent():
    websocket = FakeWebSocket()
    connection = SimpleNamespace(user_name="alice", user_uuid="user-1", websocket=websocket)
    stream = ChatStream({}, connection)
    release_workers = asyncio.Event()
    started = [asyncio.Event() for _ in range(5)]

    async def worker(started_event):
        started_event.set()
        await release_workers.wait()

    tasks = [asyncio.create_task(worker(event)) for event in started]
    stream.ingress_helper.ingress_worker_task = tasks[0]
    stream.topic_planner.processor_task = tasks[1]
    stream.topic_replier.processor_task = tasks[2]
    stream.reflection_worker.processor_task = tasks[3]
    stream.response_sender_task = tasks[4]
    await asyncio.gather(*(event.wait() for event in started))

    await stream.stop()
    await stream.stop()

    assert websocket.close_calls == 1
    assert stream.ws_connection is None
    assert all(task.done() for task in tasks)
    assert stream.ingress_helper.ingress_worker_task is None
    assert stream.topic_planner.processor_task is None
    assert stream.topic_replier.processor_task is None
    assert stream.reflection_worker.processor_task is None
    assert stream.response_sender_task is None


@pytest.mark.asyncio
async def test_chat_stream_stop_retries_after_websocket_close_failure():
    websocket = FakeWebSocket(failures=1)
    connection = SimpleNamespace(user_name="alice", user_uuid="user-1", websocket=websocket)
    stream = ChatStream({}, connection)

    with pytest.raises(RuntimeError, match="close failed"):
        await stream.stop()

    await stream.stop()
    await stream.stop()

    assert websocket.close_calls == 2


@pytest.mark.asyncio
async def test_chat_stream_manager_retains_only_failed_stream_for_retry():
    class RetryableStream:
        def __init__(self, failures=0):
            self.failures = failures
            self.stop_calls = 0

        async def stop(self, *, close_connection):
            assert close_connection is True
            self.stop_calls += 1
            if self.stop_calls <= self.failures:
                raise RuntimeError("stream stop failed")

    failed_then_ok = RetryableStream(failures=1)
    healthy = RetryableStream()
    manager = ChatStreamManager({}, None, None, None, None)
    manager.user_streams = {
        ("user-1", "luotianyi"): failed_then_ok,
        ("user-2", "luotianyi"): healthy,
    }

    with pytest.raises(RuntimeError, match="stream stop failed"):
        await manager.stop_all_streams()

    assert manager.user_streams == {("user-1", "luotianyi"): failed_then_ok}
    assert healthy.stop_calls == 1

    await manager.stop_all_streams()

    assert manager.user_streams == {}
    assert failed_then_ok.stop_calls == 2
    assert healthy.stop_calls == 1


@pytest.mark.asyncio
async def test_chat_session_shutdown_attempts_all_owned_services():
    calls = []

    class Streams:
        async def stop_all_streams(self):
            calls.append("streams")
            raise RuntimeError("stream failure")

    class Calls:
        async def stop_background_services(self):
            calls.append("calls")

    class Speaking:
        async def stop(self):
            calls.append("speaking")

    manager = object.__new__(ChatSessionManager)
    manager.chat_stream_manager = Streams()
    manager.call_stream_manager = Calls()
    manager.global_speaking_worker = Speaking()

    with pytest.raises(RuntimeError, match="Chat session shutdown failed"):
        await manager.stop_background_services()

    assert calls == ["streams", "calls", "speaking"]


class OrderedAsyncService:
    def __init__(self, calls, name, method_name, failures=0):
        self.calls = calls
        self.name = name
        self.failures = failures
        self.call_count = 0
        setattr(self, method_name, self.stop)

    async def stop(self):
        self.calls.append(self.name)
        self.call_count += 1
        if self.call_count <= self.failures:
            raise RuntimeError(f"{self.name} failed")


@pytest.mark.asyncio
async def test_system_runtime_shutdown_is_ordered_idempotent_and_retryable():
    calls = []
    chat = OrderedAsyncService(calls, "chat", "stop_background_services")
    world = OrderedAsyncService(calls, "world", "stop_background_services", failures=1)
    agent = OrderedAsyncService(calls, "agent", "shutdown")
    capability = OrderedAsyncService(calls, "capability", "stop")
    database = OrderedAsyncService(calls, "database", "shutdown")
    runtime = SystemRuntime(
        user_interface=object(),
        world=world,
        database_manager=database,
        agent_runtime=agent,
        capability_manager=capability,
        chat_session_manager=chat,
        llm_service=object(),
        observability=object(),
        client_llm_executor=ClientLLMExecutor(),
        owns_observability=False,
    )

    with pytest.raises(RuntimeError, match="world failed"):
        await runtime.shutdown()

    assert calls == ["world"]

    await runtime.shutdown()
    await runtime.shutdown()

    assert calls == ["world", "world", "chat", "agent", "capability", "database"]
    assert runtime._shutdown_complete is True


@pytest.mark.asyncio
async def test_admin_shell_keeps_retry_handle_until_runtime_cleanup_succeeds(monkeypatch):
    events = []

    class FlakySupervisor:
        def __init__(self):
            self.has_runtime = True
            self.stop_calls = 0

        async def stop(self):
            self.stop_calls += 1
            if self.stop_calls == 1:
                return {"state": "failed", "last_error": "cleanup failed"}
            self.has_runtime = False
            return {"state": "stopped", "last_error": None}

    class Observability:
        def close(self):
            events.append("observability_closed")

    shell = object.__new__(AdminShell)
    shell.runtime_supervisor = FlakySupervisor()
    shell.observability = Observability()
    monkeypatch.setattr(admin_shell_module, "_admin_shell", shell)
    monkeypatch.setattr(
        admin_shell_module,
        "set_observability_service",
        lambda value: events.append(("observability_global", value)),
    )
    monkeypatch.setattr(
        admin_shell_module,
        "uninstall_observability_log_handler",
        lambda: events.append("handler_uninstalled"),
    )

    with pytest.raises(RuntimeError, match="cleanup failed"):
        await admin_shell_module.shutdown_admin_shell()

    assert admin_shell_module._admin_shell is shell
    assert events == []

    await admin_shell_module.shutdown_admin_shell()

    assert admin_shell_module._admin_shell is None
    assert events == [
        "observability_closed",
        ("observability_global", None),
        "handler_uninstalled",
    ]


def make_supervisor():
    return RuntimeSupervisor(
        config_store=object(),
        secret_store=object(),
        validator=object(),
        observability=object(),
    )


@pytest.mark.asyncio
async def test_supervisor_retains_runtime_until_retry_succeeds():
    class FlakyRuntime:
        def __init__(self):
            self.shutdown_calls = 0

        async def shutdown(self):
            self.shutdown_calls += 1
            if self.shutdown_calls == 1:
                raise RuntimeError("shutdown failed")

    runtime = FlakyRuntime()
    supervisor = make_supervisor()
    supervisor._runtime = runtime
    supervisor.state = "running"

    failed = await supervisor.stop()

    assert failed["state"] == "failed"
    assert supervisor._runtime is runtime
    assert supervisor.runtime is None

    blocked_start = await supervisor.start()

    assert blocked_start["state"] == "failed"
    assert supervisor._runtime is runtime

    stopped = await supervisor.stop()

    assert stopped["state"] == "stopped"
    assert supervisor._runtime is None
    assert runtime.shutdown_calls == 2


@pytest.mark.asyncio
async def test_supervisor_restart_does_not_start_after_failed_shutdown():
    class FailingRuntime:
        async def shutdown(self):
            raise RuntimeError("shutdown failed")

    supervisor = make_supervisor()
    supervisor._runtime = FailingRuntime()
    supervisor.state = "running"
    start_calls = 0

    async def forbidden_start():
        nonlocal start_calls
        start_calls += 1
        return supervisor.status()

    supervisor.start = forbidden_start

    status = await supervisor.restart()

    assert status["state"] == "failed"
    assert supervisor._runtime is not None
    assert start_calls == 0
