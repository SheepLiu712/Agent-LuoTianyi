import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.adapter.websocket.call_v1 import CallWebSocketAdapter, parse_call_transport_enabled
from src.agent_runtime.agent_runtime import AgentRuntime
from src.stage import StageManager
from src.stage.call_settlement import CallRecoveryReport
from src.stage.stage_manager import CallOpenRequest


@pytest.mark.parametrize("config", [{}, {"call_transport": {}}, {"call_transport": {"enabled": False}}])
def test_call_transport_defaults_to_disabled(config):
    assert parse_call_transport_enabled(config) is False


def test_adapter_capability_defaults_fail_closed():
    manager = SimpleNamespace(
        call_settlement_ready=True,
        call_recovery_ready=True,
        is_closed=lambda: False,
    )
    adapter = CallWebSocketAdapter(manager=manager)

    assert adapter.capability_status.available is False
    assert adapter.supports_call_character("luotianyi") is False


def ready_adapter():
    manager = SimpleNamespace(
        call_settlement_ready=True,
        call_recovery_ready=True,
        is_closed=lambda: False,
    )
    return CallWebSocketAdapter(
        manager=manager,
        enabled=True,
        trusted_host=True,
        provider_ready=True,
        call_tts_character_ids=lambda: ("luotianyi",),
        call_summary_character_ids=lambda: ("luotianyi",),
    )


def test_call_capability_requires_every_public_module_readiness_fact():
    status = ready_adapter().capability_status

    assert status.enabled is True
    assert status.trusted_host is True
    assert status.provider_ready is True
    assert status.call_tts_ready is True
    assert status.summary_ready is True
    assert status.settlement_ready is True
    assert status.stage_binding_ready is True
    assert status.recovery_ready is True
    assert status.character_ids == ("luotianyi",)
    assert status.available is True


@pytest.mark.parametrize(
    "field,mutate",
    [
        ("enabled", lambda adapter: setattr(adapter, "_enabled", False)),
        ("trusted_host", lambda adapter: setattr(adapter, "_trusted_host", False)),
        ("provider_ready", lambda adapter: setattr(adapter, "_provider_ready", False)),
        ("call_tts_ready", lambda adapter: setattr(adapter, "_call_tts_character_ids", lambda: ())),
        ("summary_ready", lambda adapter: setattr(adapter, "_call_summary_character_ids", lambda: ())),
        ("settlement_ready", lambda adapter: setattr(adapter._manager, "call_settlement_ready", False)),
        ("stage_binding_ready", lambda adapter: setattr(adapter, "_closed", True)),
        ("recovery_ready", lambda adapter: setattr(adapter._manager, "call_recovery_ready", False)),
    ],
)
def test_each_missing_call_capability_fact_fails_closed(field, mutate):
    adapter = ready_adapter()
    mutate(adapter)

    status = adapter.capability_status

    assert getattr(status, field) is False
    assert status.available is False


def test_capability_and_ingress_use_the_same_character_fact():
    adapter = ready_adapter()

    assert adapter.capability_status.available is True
    assert adapter.supports_call_character("luotianyi") is True
    assert adapter.supports_call_character("other") is False


def test_agent_runtime_exposes_call_capability_without_skills_tree_access():
    runtime = object.__new__(AgentRuntime)
    runtime.character_ids = ("luotianyi", "other")
    runtime.skills = SimpleNamespace(
        speaking=SimpleNamespace(supports_call_audio=lambda character_id: character_id == "luotianyi"),
        prepared_speech=SimpleNamespace(supports_call_apology=lambda character_id: character_id == "luotianyi"),
        call_summary=SimpleNamespace(supports_character=lambda character_id: character_id == "luotianyi"),
    )

    assert runtime.call_tts_character_ids == ("luotianyi",)
    assert runtime.call_summary_character_ids == ("luotianyi",)


@pytest.mark.asyncio
async def test_manager_rejects_call_admission_until_recovery_completes():
    manager = object.__new__(StageManager)
    manager._closed = False
    manager._call_settlement = SimpleNamespace(is_ready=True)
    manager._recovery_ready = False
    entered, release = asyncio.Event(), asyncio.Event()

    class Recovery:
        async def reconcile(self):
            entered.set()
            await release.wait()
            return CallRecoveryReport(0, 0, 0, 0, 0)

    manager._stale_call_recovery = Recovery()
    manager._initialization = None
    initializing = asyncio.create_task(manager.initialize())
    await entered.wait()

    with pytest.raises(RuntimeError, match="CALL_INGRESS_UNAVAILABLE"):
        await manager.open_call(
            CallOpenRequest("user", "luotianyi", "request"),
            SimpleNamespace(),
        )

    release.set()
    await initializing
    assert manager.call_recovery_ready is True


@pytest.mark.asyncio
async def test_manager_initialize_is_owned_idempotent_and_runs_recovery_once():
    manager = object.__new__(StageManager)
    manager._closed = False
    manager._call_settlement = SimpleNamespace(is_ready=True)
    manager._recovery_ready = False
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0

    class Recovery:
        async def reconcile(self):
            nonlocal calls
            calls += 1
            entered.set()
            await release.wait()
            return CallRecoveryReport(0, 0, 0, 0, 0)

    manager._stale_call_recovery = Recovery()
    manager._initialization = None
    first = asyncio.create_task(manager.initialize())
    await entered.wait()
    first.cancel()
    second = asyncio.create_task(manager.initialize())
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await first
    await second
    await manager.initialize()

    assert calls == 1
    assert manager.call_recovery_ready is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "report",
    [
        CallRecoveryReport(1, 0, 0, 0, 1),
        CallRecoveryReport(1, 0, 0, 1, 0),
    ],
)
async def test_manager_initialize_failure_remains_not_ready(report):
    manager = object.__new__(StageManager)
    manager._closed = False
    manager._call_settlement = SimpleNamespace(is_ready=True)
    manager._recovery_ready = False
    manager._initialization = None
    manager._stale_call_recovery = SimpleNamespace(reconcile=lambda: _report(report))

    with pytest.raises(RuntimeError, match="did not converge"):
        await manager.initialize()

    assert manager.call_recovery_ready is False


@pytest.mark.asyncio
async def test_manager_close_waits_for_owned_recovery_and_late_success_stays_not_ready():
    manager = _manager_with_blocking_thread_recovery()
    initializing = asyncio.create_task(manager.initialize())
    await asyncio.wait_for(manager._test_recovery_entered.wait(), 1)

    closing = asyncio.create_task(manager.close())
    await asyncio.sleep(0)

    assert closing.done() is False
    assert manager.call_recovery_ready is False
    assert manager.call_business_ready is False
    manager._test_recovery_release.set()
    await asyncio.wait_for(closing, 2)
    with pytest.raises(RuntimeError, match="closed during initialization"):
        await initializing
    assert manager.call_recovery_ready is False
    assert manager.call_business_ready is False


@pytest.mark.asyncio
async def test_manager_close_drains_failed_initialization_without_unobserved_task(caplog):
    manager = _manager_with_blocking_thread_recovery(error=RuntimeError("recovery failed"))
    initializing = asyncio.create_task(manager.initialize())
    await asyncio.wait_for(manager._test_recovery_entered.wait(), 1)
    closing = asyncio.create_task(manager.close())
    await asyncio.sleep(0)
    manager._test_recovery_release.set()

    await asyncio.wait_for(closing, 2)
    with pytest.raises(RuntimeError, match="recovery failed"):
        await initializing
    await asyncio.sleep(0)
    assert "Task exception was never retrieved" not in caplog.text
    assert manager.call_recovery_ready is False


@pytest.mark.asyncio
async def test_cancelled_initialize_waiters_do_not_cancel_owner_and_close_drains_it():
    manager = _manager_with_blocking_thread_recovery()
    first = asyncio.create_task(manager.initialize())
    second = asyncio.create_task(manager.initialize())
    await asyncio.wait_for(manager._test_recovery_entered.wait(), 1)
    first.cancel()
    second.cancel()
    closing = asyncio.create_task(manager.close())
    manager._test_recovery_release.set()

    with pytest.raises(asyncio.CancelledError):
        await first
    with pytest.raises(asyncio.CancelledError):
        await second
    await asyncio.wait_for(closing, 2)
    assert manager._test_recovery_calls == 1
    assert manager.call_recovery_ready is False


def _manager_with_blocking_thread_recovery(*, error=None):
    manager = StageManager(
        get_agent=lambda _character: object(),
        adapter=SimpleNamespace(),
        get_context_factory=lambda _character: object(),
    )
    manager._recovery_ready = False
    manager._test_recovery_entered = asyncio.Event()
    manager._test_recovery_release = threading.Event()
    manager._test_recovery_calls = 0

    class Recovery:
        async def reconcile(self):
            manager._test_recovery_calls += 1
            loop = asyncio.get_running_loop()

            def blocking_recovery():
                loop.call_soon_threadsafe(manager._test_recovery_entered.set)
                manager._test_recovery_release.wait()
                if error is not None:
                    raise error
                return CallRecoveryReport(0, 0, 0, 0, 0)

            return await asyncio.to_thread(blocking_recovery)

    manager._stale_call_recovery = Recovery()
    return manager


async def _report(value):
    return value


def test_composition_root_does_not_traverse_call_module_internals():
    source = (Path(__file__).resolve().parents[2] / "src" / "server_runtime.py").read_text(encoding="utf-8")

    for forbidden in (
        "agent_runtime.skills",
        "CallTransportHub",
        "CallStageBinding",
        "StaleCallRecoveryService",
        "stale_call_recovery.reconcile",
    ):
        assert forbidden not in source


@pytest.mark.parametrize("value", ["false", 1, None, [], {}])
def test_call_transport_rejects_non_boolean_enabled_values(value):
    with pytest.raises(ValueError, match="call_transport.enabled"):
        parse_call_transport_enabled({"call_transport": {"enabled": value}})


def test_call_transport_rejects_non_object_section():
    with pytest.raises(ValueError, match="call_transport must be an object"):
        parse_call_transport_enabled({"call_transport": False})
