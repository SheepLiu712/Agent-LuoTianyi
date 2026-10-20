from pathlib import Path
from types import SimpleNamespace

import pytest

from src.adapter.websocket.call_v1 import CallWebSocketAdapter, parse_call_transport_enabled
from src.agent_runtime.agent_runtime import AgentRuntime
from src.stage import StageManager


@pytest.mark.parametrize("config", [{}, {"call_transport": {}}, {"call_transport": {"enabled": False}}])
def test_call_transport_defaults_to_disabled(config):
    assert parse_call_transport_enabled(config) is False


def test_adapter_capability_defaults_fail_closed():
    manager = SimpleNamespace(
        call_business_ready=True,
        is_closed=lambda: False,
    )
    adapter = CallWebSocketAdapter(manager=manager)

    assert adapter.capability_status.available is False
    assert adapter.supports_call_character("luotianyi") is False


def ready_adapter():
    manager = SimpleNamespace(
        call_business_ready=True,
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
        ("settlement_ready", lambda adapter: setattr(adapter._manager, "call_business_ready", False)),
        ("stage_binding_ready", lambda adapter: setattr(adapter, "_closed", True)),
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
async def test_manager_initialization_does_not_replay_durable_calls():
    class Records:
        def __getattr__(self, name):
            raise AssertionError("startup must not access old calls")

    manager = object.__new__(StageManager)
    manager._closed = False
    manager._call_records = Records()
    manager._call_stage_creator = lambda: None
    await manager.initialize()
    await manager.initialize()
    assert manager.call_business_ready
    manager._closed = True
    with pytest.raises(RuntimeError, match="closed during initialization"):
        await manager.initialize()
    assert not manager.call_business_ready


def test_composition_root_does_not_traverse_call_module_internals():
    source = (Path(__file__).resolve().parents[2] / "src" / "server_runtime.py").read_text(encoding="utf-8")

    for forbidden in (
        "agent_runtime.skills",
        "_CallTransportHub",
        "_CallStageBinding",
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
