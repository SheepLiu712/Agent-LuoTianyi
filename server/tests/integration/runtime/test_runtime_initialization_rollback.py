import asyncio
import json
import threading
from importlib.resources import files
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from support.chat_connection import StubChatConnection
from support.stage_manager import make_stage_manager
from support.stage_support import RecordingAgent, StageContextFactory, report

import src.server_runtime as runtime_module
from src.adapter.websocket.chat import WebSocketAdapter
from src.agent_runtime import agent_runtime as agent_runtime_module
from src.agent_runtime.agent_runtime import AgentRuntime
from src.application.user.agreement_service import init_agreements
from src.domain.stage.lifecycle import StageEndReason
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


class EmptyCallSessions:
    def list_termination_pending(self):
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
        self.character_ids = ("luotianyi",)
        self.context_factories = {"luotianyi": object()}
        self.singing_backend = object()
        self.vector_store = object()
        self.call_tts_character_ids = ()
        self.call_summary_character_ids = ()

    async def extract_imported_memories(self, *_args):
        pytest.fail("runtime initialization must not extract imported memories")

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
        self.call_sessions = EmptyCallSessions()
        self.call_maintenance_batches = object()
        self.conversation_service = object()
        self.memory_store = object()
        self.user_store = object()
        self.redis = object()
        # 注册用例需要凭据服务；这里只要求属性存在，测试用不到它的行为。
        self.credential_service = SimpleNamespace()
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

    monkeypatch.setattr(runtime_module, "ObservabilityService", lambda _config, **_kwargs: FakeObservability(calls))
    monkeypatch.setattr(runtime_module, "LLMService", FakeLLM)
    monkeypatch.setattr(runtime_module, "DatabaseManager", lambda _config: FakeDatabase(calls, SessionLocal))
    monkeypatch.setattr(runtime_module, "create_media_resolver", lambda _config: FakeMediaResolver())
    monkeypatch.setattr(
        runtime_module,
        "WorldRuntime",
        lambda config, **kwargs: FakeWorld(config, calls=calls, **kwargs),
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
        await runtime_module.ServerRuntime.initialize(
            {"infrastructure": {"media_resolution": {"root": str(tmp_path / "media")}}}
        )

    assert calls.index("world_started") < calls.index("rsa_generation_failed")
    assert calls.index("world_stopped") < calls.index("database_stopped")
    assert database_ref["value"] is None
    assert observability_ref["value"] is None
    assert "observability_closed" in calls
    assert "observability_handler_uninstalled" in calls

    _assert_failed_release_did_not_archive(SessionLocal, tmp_path)
    engine.dispose()


@pytest.mark.asyncio
async def test_initialization_rollback_waits_for_stage_manager_before_agent_and_database():
    calls = []
    stage_release = asyncio.Event()

    runtime = rollback_runtime(
        calls,
        SimpleNamespace(
            close=lambda: _record_wait(calls, "stage_manager_started", "stage_manager_stopped", stage_release)
        ),
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
        if "stage_manager_started" in calls:
            break
        await asyncio.sleep(0)
    assert "agent" not in calls and "database" not in calls
    stage_release.set()
    await rollback
    assert calls.index("stage_manager_stopped") < calls.index("agent") < calls.index("database")


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_count", [1, 2])
async def test_cancelled_runtime_rollback_drains_real_manager_termination_before_dependencies(
    cancel_count,
):
    calls = []
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()

    class Termination:
        async def reconcile(self):
            def blocking_termination():
                loop.call_soon_threadsafe(entered.set)
                release.wait()
                calls.append("termination_stopped")
                return None

            return await asyncio.to_thread(blocking_termination)

    manager, initializing = await _start_managed_chat_termination(Termination().reconcile)
    await entered.wait()

    runtime = rollback_runtime(calls, manager)
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
    await initializing
    assert done_before_release is False
    assert dependencies_closed_before_release is False
    assert result_before_release is None
    assert isinstance(result[0], asyncio.CancelledError)
    assert calls.index("termination_stopped") < calls.index("agent") < calls.index("database")


@pytest.mark.asyncio
async def test_cancelled_runtime_rollback_continues_after_termination_and_stop_failures(
    caplog,
):
    calls = []
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()

    class Termination:
        async def reconcile(self):
            def blocking_termination():
                loop.call_soon_threadsafe(entered.set)
                release.wait()
                calls.append("termination_stopped")
                raise RuntimeError("termination internal detail")

            return await asyncio.to_thread(blocking_termination)

    manager, initializing = await _start_managed_chat_termination(Termination().reconcile)
    await entered.wait()

    async def failing_world_stop():
        calls.append("world")
        raise RuntimeError("world internal detail")

    runtime = rollback_runtime(calls, manager)
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
    termination_result = await initializing
    assert termination_result.finalization_error == "RuntimeError"
    assert termination_result.resources_released
    assert dependencies_closed_before_release is False
    assert done_before_release is False
    assert isinstance(result[0], asyncio.CancelledError)
    assert calls.index("termination_stopped") < calls.index("agent") < calls.index("database")
    assert "world internal detail" not in caplog.text
    assert "Task exception was never retrieved" not in caplog.text


def rollback_runtime(calls, manager):
    """Use the real lifecycle owner; only external dependencies are test doubles."""
    runtime = runtime_module.ServerRuntime(
        agreement_service=None,
        registration_service=None,
        user_interface=None,
        websocket_service=None,
        world=None,
        database_manager=None,
        agent_runtime=None,
        media_resolver=None,
        llm_service=None,
        client_llm_executor=None,
        observability=None,
        owns_observability=False,
        stage_manager=manager,
        chat_adapter=SimpleNamespace(close=lambda: _record(calls, "chat_adapter")),
        call_adapter=SimpleNamespace(close=lambda: _record(calls, "transport")),
    )
    runtime.close_world_stages = lambda: _record(calls, "world_stages")
    return runtime


async def _record(calls, value):
    calls.append(value)


async def _start_managed_chat_termination(operation):
    async def handle(request, sink):
        await operation()
        return report(request)

    manager = make_stage_manager(
        get_agent=lambda _: RecordingAgent(handle=handle),
        adapter=WebSocketAdapter(),
        get_context_factory=lambda _: StageContextFactory(),
    )
    stage = await manager.try_to_get_stage(
        user_id="user", character_id="luotianyi", connection=StubChatConnection(None, "user", "user")
    )
    await stage.start()
    return manager, asyncio.create_task(stage.terminate(StageEndReason.SHUTDOWN))


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
