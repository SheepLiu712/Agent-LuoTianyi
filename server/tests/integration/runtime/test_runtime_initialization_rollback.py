import asyncio
import threading
from types import SimpleNamespace

import pytest

import src.server_runtime as runtime_module
from src.adapter.websocket import WebSocketAdapter
from src.agent_runtime import agent_runtime as agent_runtime_module
from src.agent_runtime.agent_runtime import AgentRuntime
from src.infrastructure.persistence.database import vector_store as vector_store_module
from src.infrastructure.persistence.database.vector_store import ChromaVectorStore
from src.stage import StageManager
from src.stage.call_settlement import CallRecoveryReport


class FakeLLM:
    def __init__(self, _config, client_llm_executor):
        pass

    def ensure_dependencies(self):
        pass


class FakeMediaResolver:
    def ensure_dependencies(self):
        pass


class EmptyCallSessions:
    def list_recovery_pending(self):
        return []

    def find_by_id(self, _call_id):
        return None


class FakeWorld:
    def __init__(self, _config, *, calls, **_kwargs):
        self.calls = calls

    def wire_dependencies(self, **_kwargs):
        pass

    def ensure_dependencies(self):
        pass

    def start_background_services(self):
        self.calls.append("world_started")

    async def stop_background_services(self):
        self.calls.append("world_stopped")


class FakeAgentRuntime:
    def __init__(self, *_args, **_kwargs):
        self.default_character_id = "luotianyi"
        self.context_factories = {"luotianyi": object()}
        self.singing_backend = object()
        self.vector_store = object()
        self.call_tts_character_ids = ()
        self.call_summary_character_ids = ()

    def release_call_maintenance(self, _call_id):
        pass

    def release_call_resources(self, _call_id):
        return False

    def get_agent(self, _character_id=None):
        return object()

    def wire_dependencies(self, **_kwargs):
        pass

    def ensure_dependencies(self):
        pass


@pytest.mark.asyncio
async def test_late_initialization_failure_rolls_back_resources_and_globals(monkeypatch, tmp_path):
    calls = []
    database_ref = {"value": None}
    observability_ref = {"value": None}

    class FakeObservability:
        def __init__(self, _config, **_kwargs):
            calls.append("observability_created")

        def close(self):
            calls.append("observability_closed")

    class FakeDatabase:
        def __init__(self, _config):
            calls.append("database_created")
            self.event_store = object()
            self.call_sessions = EmptyCallSessions()
            self.call_maintenance_batches = object()
            self.conversation_service = object()
            self.memory_store = object()
            self.user_store = object()
            self.redis = object()

        def wire_dependencies(self, **_kwargs):
            pass

        def ensure_dependencies(self):
            pass

        async def shutdown(self):
            calls.append("database_stopped")

    class FailingUserInterface(runtime_module.UserInterface):
        def generate_rsa_keys(self):
            # Exercise production constructor/validation and verify the shared injected resolver.
            assert self.database_manager is database_ref["value"]
            assert self.user_conversation_helper.database_manager is self.database_manager
            assert self.user_conversation_helper.media_resolver is self.media_resolver
            assert isinstance(self.media_resolver, FakeMediaResolver)
            calls.append("rsa_generation_failed")
            raise RuntimeError("late initialization failure")

    def set_database(value):
        database_ref["value"] = value
        calls.append("database_global_set" if value is not None else "database_global_cleared")

    def set_observability(value):
        observability_ref["value"] = value
        calls.append("observability_global_set" if value is not None else "observability_global_cleared")

    monkeypatch.setattr(runtime_module, "ObservabilityService", FakeObservability)
    monkeypatch.setattr(runtime_module, "LLMService", FakeLLM)
    monkeypatch.setattr(runtime_module, "DatabaseManager", FakeDatabase)
    monkeypatch.setattr(runtime_module, "create_media_resolver", lambda _config: FakeMediaResolver())
    monkeypatch.setattr(
        runtime_module, "WorldRuntime", lambda config, **kwargs: FakeWorld(config, calls=calls, **kwargs)
    )
    monkeypatch.setattr(runtime_module, "AgentRuntime", FakeAgentRuntime)
    monkeypatch.setattr(runtime_module, "UserInterface", FailingUserInterface)
    monkeypatch.setattr(runtime_module, "set_default_database_manager", set_database)
    monkeypatch.setattr(runtime_module, "set_observability_service", set_observability)
    monkeypatch.setattr(
        runtime_module,
        "install_observability_log_handler",
        lambda _observability: calls.append("observability_handler_installed"),
    )
    monkeypatch.setattr(
        runtime_module,
        "uninstall_observability_log_handler",
        lambda: calls.append("observability_handler_uninstalled"),
    )
    monkeypatch.setattr(runtime_module, "_server_runtime", None)

    with pytest.raises(RuntimeError, match="late initialization failure"):
        await runtime_module.ServerRuntime.initialize(
            {"infrastructure": {"media_resolution": {"root": str(tmp_path / "media")}}}
        )

    assert calls.index("world_started") < calls.index("rsa_generation_failed")
    assert calls.index("world_stopped") < calls.index("database_stopped")
    assert database_ref["value"] is None
    assert observability_ref["value"] is None
    assert "observability_closed" in calls
    assert "observability_handler_uninstalled" in calls


@pytest.mark.asyncio
async def test_initialization_rollback_waits_for_stage_manager_before_agent_and_database():
    calls = []
    stage_release = asyncio.Event()

    class Runtime:
        async def close_world_stages(self):
            calls.append("world_stages")

        stage_manager = SimpleNamespace(
            close=lambda: _record_wait(calls, "stage_manager_started", "stage_manager_stopped", stage_release)
        )
        call_adapter = SimpleNamespace(close=lambda: _record(calls, "transport"))

    world = SimpleNamespace(stop_background_services=lambda: _record(calls, "world"))
    agent = SimpleNamespace(shutdown=lambda: _record(calls, "agent"))
    database = SimpleNamespace(shutdown=lambda: _record(calls, "database"))
    rollback = asyncio.create_task(
        runtime_module.ServerRuntime._rollback_failed_initialization(
            runtime=Runtime(),
            world=world,
            database_manager=database,
            agent_runtime=agent,
            observability=None,
            owns_observability=False,
        )
    )
    for _ in range(100):
        if "stage_manager_started" in calls:
            break
        await asyncio.sleep(0)
    assert "agent" not in calls and "database" not in calls
    stage_release.set()
    await rollback
    assert calls.index("stage_manager_stopped") < calls.index("agent") < calls.index("database")


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_count", [1, 2])
async def test_cancelled_runtime_rollback_drains_real_manager_recovery_before_dependencies(cancel_count):
    calls = []
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    manager = StageManager(
        get_agent=lambda _character: object(),
        adapter=WebSocketAdapter(),
        get_context_factory=lambda _character: object(),
    )
    manager._recovery_ready = False

    class Recovery:
        async def reconcile(self):
            def blocking_recovery():
                loop.call_soon_threadsafe(entered.set)
                release.wait()
                calls.append("recovery_stopped")
                return CallRecoveryReport(0, 0, 0, 0, 0)

            return await asyncio.to_thread(blocking_recovery)

    manager._stale_call_recovery = Recovery()
    initializing = asyncio.create_task(manager.initialize())
    await entered.wait()

    runtime = SimpleNamespace(
        close_world_stages=lambda: _record(calls, "world_stages"),
        stage_manager=manager,
        call_adapter=SimpleNamespace(close=lambda: _record(calls, "transport")),
    )
    world = SimpleNamespace(stop_background_services=lambda: _record(calls, "world"))
    agent = SimpleNamespace(shutdown=lambda: _record(calls, "agent"))
    database = SimpleNamespace(shutdown=lambda: _record(calls, "database"))
    rollback = asyncio.create_task(
        runtime_module.ServerRuntime._rollback_failed_initialization(
            runtime=runtime,
            world=world,
            database_manager=database,
            agent_runtime=agent,
            observability=None,
            owns_observability=False,
        )
    )
    for _ in range(100):
        if manager._closing is not None:
            break
        await asyncio.sleep(0)
    for _ in range(cancel_count):
        rollback.cancel()
        await asyncio.sleep(0)

    done_before_release = rollback.done()
    result_before_release = None
    if done_before_release:
        result_before_release = type(rollback.exception()).__name__ if rollback.exception() is not None else "success"
    dependencies_closed_before_release = "agent" in calls or "database" in calls
    release.set()
    result = await asyncio.gather(rollback, return_exceptions=True)
    with pytest.raises(RuntimeError, match="closed during initialization"):
        await initializing
    assert done_before_release is False
    assert dependencies_closed_before_release is False
    assert result_before_release is None
    assert isinstance(result[0], asyncio.CancelledError)
    assert calls.index("recovery_stopped") < calls.index("agent") < calls.index("database")


@pytest.mark.asyncio
async def test_cancelled_runtime_rollback_continues_after_recovery_and_stop_failures(caplog):
    calls = []
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    manager = StageManager(
        get_agent=lambda _character: object(),
        adapter=WebSocketAdapter(),
        get_context_factory=lambda _character: object(),
    )
    manager._recovery_ready = False

    class Recovery:
        async def reconcile(self):
            def blocking_recovery():
                loop.call_soon_threadsafe(entered.set)
                release.wait()
                calls.append("recovery_stopped")
                raise RuntimeError("recovery internal detail")

            return await asyncio.to_thread(blocking_recovery)

    manager._stale_call_recovery = Recovery()
    initializing = asyncio.create_task(manager.initialize())
    await entered.wait()

    async def failing_world_stop():
        calls.append("world")
        raise RuntimeError("world internal detail")

    runtime = SimpleNamespace(
        close_world_stages=lambda: _record(calls, "world_stages"),
        stage_manager=manager,
        call_adapter=SimpleNamespace(close=lambda: _record(calls, "transport")),
    )
    rollback = asyncio.create_task(
        runtime_module.ServerRuntime._rollback_failed_initialization(
            runtime=runtime,
            world=SimpleNamespace(stop_background_services=failing_world_stop),
            database_manager=SimpleNamespace(shutdown=lambda: _record(calls, "database")),
            agent_runtime=SimpleNamespace(shutdown=lambda: _record(calls, "agent")),
            observability=None,
            owns_observability=False,
        )
    )
    for _ in range(100):
        if manager._closing is not None:
            break
        await asyncio.sleep(0)
    rollback.cancel()
    await asyncio.sleep(0)
    done_before_release = rollback.done()
    dependencies_closed_before_release = "agent" in calls or "database" in calls
    release.set()

    result = await asyncio.gather(rollback, return_exceptions=True)
    with pytest.raises(RuntimeError, match="recovery internal detail"):
        await initializing
    assert dependencies_closed_before_release is False
    assert done_before_release is False
    assert isinstance(result[0], asyncio.CancelledError)
    assert calls.index("recovery_stopped") < calls.index("agent") < calls.index("database")
    assert "world internal detail" not in caplog.text
    assert "Task exception was never retrieved" not in caplog.text


async def _record(calls, value):
    calls.append(value)


async def _record_wait(calls, started, stopped, release):
    calls.append(started)
    await release.wait()
    calls.append(stopped)


@pytest.mark.asyncio
async def test_agent_runtime_shutdown_closes_owned_vector_store_once(monkeypatch):
    class FakeVectorStore:
        def __init__(self):
            self.close_calls = 0

        def close(self):
            self.close_calls += 1

    vector_store = FakeVectorStore()
    runtime = object.__new__(AgentRuntime)
    runtime.vector_store = vector_store
    runtime._shutdown_lock = asyncio.Lock()
    runtime._shutdown_complete = False
    monkeypatch.setattr(agent_runtime_module, "_agent_runtime", runtime)
    monkeypatch.setattr(vector_store_module, "vector_store", vector_store)

    await runtime.shutdown()
    await runtime.shutdown()

    assert vector_store.close_calls == 1
    assert agent_runtime_module._agent_runtime is None
    assert vector_store_module.vector_store is None


@pytest.mark.asyncio
async def test_old_agent_shutdown_preserves_replacement_globals(monkeypatch):
    class FakeVectorStore:
        def __init__(self):
            self.close_calls = 0

        def close(self):
            self.close_calls += 1

    old_store = FakeVectorStore()
    replacement_store = FakeVectorStore()
    old_runtime = object.__new__(AgentRuntime)
    old_runtime.vector_store = old_store
    old_runtime._shutdown_lock = asyncio.Lock()
    old_runtime._shutdown_complete = False
    replacement_runtime = object()
    monkeypatch.setattr(agent_runtime_module, "_agent_runtime", replacement_runtime)
    monkeypatch.setattr(vector_store_module, "vector_store", replacement_store)

    await old_runtime.shutdown()

    assert old_store.close_calls == 1
    assert agent_runtime_module._agent_runtime is replacement_runtime
    assert vector_store_module.vector_store is replacement_store


def test_chroma_vector_store_close_is_idempotent():
    class FakeExecutor:
        def __init__(self):
            self.shutdown_calls = []

        def shutdown(self, *, wait, cancel_futures):
            self.shutdown_calls.append((wait, cancel_futures))

    executor = FakeExecutor()
    store = object.__new__(ChromaVectorStore)
    store._executor = executor
    store._close_lock = threading.Lock()
    store._closed = False

    store.close()
    store.close()

    assert executor.shutdown_calls == [(True, False)]
    assert store._closed is True
