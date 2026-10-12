import asyncio
import json
import threading
from importlib.resources import files

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import src.server_runtime as runtime_module
from src.agent_runtime import agent_runtime as agent_runtime_module
from src.agent_runtime.agent_runtime import AgentRuntime
from src.application.user.agreement_service import init_agreements
from src.infrastructure.persistence.database import vector_store as vector_store_module
from src.infrastructure.persistence.database.sql_database import AgreementVersion, Base
from src.infrastructure.persistence.database.vector_store import ChromaVectorStore


class FakeLLM:
    def __init__(self, _config, client_llm_executor):
        pass

    def ensure_dependencies(self):
        pass


class FakeMediaResolver:
    def ensure_dependencies(self):
        pass


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

    def get_agent(self, _character_id=None):
        return object()

    def wire_dependencies(self, **_kwargs):
        pass

    def ensure_dependencies(self):
        pass


class FakeObservability:
    def __init__(self, calls):
        self.calls = calls
        calls.append("observability_created")

    def close(self):
        self.calls.append("observability_closed")


class FakeDatabase:
    def __init__(self, calls, session_factory):
        self.calls = calls
        self.session_factory = session_factory
        self.event_store = object()
        calls.append("database_created")

    def open_sql_session(self):
        return self.session_factory()

    def wire_dependencies(self, **_kwargs):
        pass

    def ensure_dependencies(self):
        pass

    async def shutdown(self):
        self.calls.append("database_stopped")


class FailingUserInterface(runtime_module.UserInterface):
    def __init__(self, database_manager, media_resolver, *, calls, database_ref):
        super().__init__(database_manager, media_resolver)
        self.calls = calls
        self.database_ref = database_ref

    def generate_rsa_keys(self):
        assert self.database_manager is self.database_ref["value"]
        assert self.user_conversation_helper.database_manager is self.database_manager
        assert self.user_conversation_helper.media_resolver is self.media_resolver
        assert isinstance(self.media_resolver, FakeMediaResolver)
        self.calls.append("rsa_generation_failed")
        raise RuntimeError("late initialization failure")


def _record_global(ref, calls, name, value) -> None:
    ref["value"] = value
    calls.append(f"{name}_{'set' if value is not None else 'cleared'}")


def _assert_failed_release_did_not_archive(SessionLocal, tmp_path) -> None:
    with SessionLocal() as session:
        assert session.query(AgreementVersion).all() == []

        old_root = tmp_path / "old_release"
        old_root.mkdir()
        packaged_root = files("res.user_agreements")
        manifest = json.loads(packaged_root.joinpath("manifest.json").read_text(encoding="utf-8"))
        first_version, first_filename = next(iter(manifest["files"].items()))
        (old_root / "manifest.json").write_text(
            json.dumps(
                {"current_version": first_version, "files": {first_version: first_filename}},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (old_root / first_filename).write_text(
            packaged_root.joinpath(first_filename).read_text(encoding="utf-8"),
            encoding="utf-8",
        )

        service = init_agreements(session, old_root)
        assert service.get_current().version == first_version
        assert [row.version for row in session.query(AgreementVersion).all()] == [first_version]


@pytest.mark.asyncio
async def test_late_initialization_failure_rolls_back_resources_and_globals(monkeypatch, tmp_path):
    calls = []
    database_ref = {"value": None}
    observability_ref = {"value": None}
    database_path = tmp_path / "runtime.db"
    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)

    monkeypatch.setattr(runtime_module, "ObservabilityService", lambda _config: FakeObservability(calls))
    monkeypatch.setattr(runtime_module, "LLMService", FakeLLM)
    monkeypatch.setattr(runtime_module, "DatabaseManager", lambda _config: FakeDatabase(calls, SessionLocal))
    monkeypatch.setattr(runtime_module, "create_media_resolver", lambda _config: FakeMediaResolver())
    monkeypatch.setattr(
        runtime_module, "WorldRuntime", lambda config, **kwargs: FakeWorld(config, calls=calls, **kwargs)
    )
    monkeypatch.setattr(runtime_module, "AgentRuntime", FakeAgentRuntime)
    monkeypatch.setattr(
        runtime_module,
        "UserInterface",
        lambda database, resolver: FailingUserInterface(
            database,
            resolver,
            calls=calls,
            database_ref=database_ref,
        ),
    )
    monkeypatch.setattr(
        runtime_module,
        "set_default_database_manager",
        lambda value: _record_global(database_ref, calls, "database_global", value),
    )
    monkeypatch.setattr(
        runtime_module,
        "set_observability_service",
        lambda value: _record_global(observability_ref, calls, "observability_global", value),
    )
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
        await runtime_module.ServerRuntime.initialize({})

    assert calls.index("world_started") < calls.index("rsa_generation_failed")
    assert calls.index("world_stopped") < calls.index("database_stopped")
    assert database_ref["value"] is None
    assert observability_ref["value"] is None
    assert "observability_closed" in calls
    assert "observability_handler_uninstalled" in calls

    _assert_failed_release_did_not_archive(SessionLocal, tmp_path)
    engine.dispose()


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
