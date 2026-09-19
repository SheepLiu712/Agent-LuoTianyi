import sys
from pathlib import Path

import pytest


server_root = str(Path(__file__).resolve().parents[3])
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.system.admin import admin_shell as admin_shell_module
from src.system.admin.admin_shell import AdminShell
from src.system.admin.runtime_supervisor import RuntimeSupervisor
from src.system.system_runtime import SystemRuntime
from src.utils.llm.client_llm_executor import ClientLLMExecutor


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
    world = OrderedAsyncService(calls, "world", "stop_background_services", failures=1)
    agent = OrderedAsyncService(calls, "agent", "shutdown")
    capability = OrderedAsyncService(calls, "capability", "stop")
    database = OrderedAsyncService(calls, "database", "shutdown")
    runtime = SystemRuntime(
        user_interface=object(),
        world=world,
        database_manager=database,
        agent_runtime=agent,
        infrastructure=capability,
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

    assert calls == ["world", "world", "agent", "capability", "database"]
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
