import asyncio
import sys
import threading
from pathlib import Path

import pytest


server_root = str(Path(__file__).resolve().parents[3])
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.agent_runtime import agent_runtime as agent_runtime_module
from src.agent_runtime.agent_runtime import AgentRuntime
from src.system import system_runtime as runtime_module
from src.system.database import vector_store as vector_store_module
from src.system.database.vector_store import ChromaVectorStore


@pytest.mark.asyncio
async def test_late_initialization_failure_rolls_back_resources_and_globals(monkeypatch):
    calls = []
    database_ref = {"value": None}
    observability_ref = {"value": None}

    class FakeObservability:
        def __init__(self, _config):
            calls.append("observability_created")

        def close(self):
            calls.append("observability_closed")

    class FakeLLM:
        def __init__(self, _config, client_llm_executor):
            pass

        def ensure_dependencies(self):
            pass

    class FakeDatabase:
        def __init__(self, _config):
            calls.append("database_created")
            self.event_store = object()

        def wire_dependencies(self, **_kwargs):
            pass

        def ensure_dependencies(self):
            pass

        async def shutdown(self):
            calls.append("database_stopped")

    class FakeInfrastructure:
        def __init__(self, _config, _llm):
            calls.append("tts_started")

        def wire_dependencies(self, **_kwargs):
            pass

        def ensure_dependencies(self):
            pass

        async def stop(self):
            calls.append("tts_stopped")

    class FakeWorld:
        def __init__(self, _config):
            pass

        def wire_dependencies(self, **_kwargs):
            pass

        def ensure_dependencies(self):
            pass

        def start_background_services(self):
            calls.append("world_started")

        async def stop_background_services(self):
            calls.append("world_stopped")

    class FakeAgentRuntime:
        def __init__(self, *_args):
            self.default_character_id = "luotianyi"
            self.context_factories = {"luotianyi": object()}

        def get_agent(self, _character_id=None):
            return object()

        def wire_dependencies(self, **_kwargs):
            pass

        def ensure_dependencies(self):
            pass

    class FailingUserInterface:
        def __init__(self, _database):
            pass

        def wire_dependencies(self, **_kwargs):
            pass

        def ensure_dependencies(self):
            pass

        def generate_rsa_keys(self):
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
    monkeypatch.setattr(runtime_module, "InfrastructureRuntime", FakeInfrastructure)
    monkeypatch.setattr(runtime_module, "WorldRuntime", FakeWorld)
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
    monkeypatch.setattr(runtime_module, "_system_runtime", None)

    with pytest.raises(RuntimeError, match="late initialization failure"):
        await runtime_module.SystemRuntime.initialize({})

    assert calls.index("world_started") < calls.index("rsa_generation_failed")
    assert calls.index("world_stopped") < calls.index("tts_stopped")
    assert calls.index("tts_stopped") < calls.index("database_stopped")
    assert database_ref["value"] is None
    assert observability_ref["value"] is None
    assert "observability_closed" in calls
    assert "observability_handler_uninstalled" in calls


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
