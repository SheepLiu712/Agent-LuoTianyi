from types import SimpleNamespace

import pytest

from src.adapter.websocket.call_v1 import CallTransportHub, parse_call_transport_enabled
from src.application.host_context import ServerHostContext
from src.server_runtime import CallCapabilityStatus, ServerRuntime
from src.stage import StageManager


@pytest.mark.parametrize("config", [{}, {"call_transport": {}}, {"call_transport": {"enabled": False}}])
def test_call_transport_defaults_to_disabled(config):
    assert parse_call_transport_enabled(config) is False


def ready_runtime():
    speaking = SimpleNamespace(supports_call_audio=lambda character_id: character_id == "luotianyi")
    summary = SimpleNamespace(supports_character=lambda character_id: character_id == "luotianyi")
    return SimpleNamespace(
        _call_transport_requested=True,
        _host_context=ServerHostContext._single_worker_launcher(),
        realtime_speech_factory=SimpleNamespace(is_configured=True),
        agent_runtime=SimpleNamespace(
            default_character_id="luotianyi",
            skills=SimpleNamespace(
                speaking=speaking,
                call_summary=summary,
                prepared_speech=SimpleNamespace(supports_call_apology=lambda _character: True),
            ),
        ),
        call_settlement_coordinator=SimpleNamespace(is_ready=True),
        stage_manager=StageManager.__new__(StageManager),
        call_transport_hub=CallTransportHub(),
        stale_call_recovery=SimpleNamespace(),
    )


def test_call_capability_requires_every_structural_readiness_fact():
    runtime = ready_runtime()
    status = ServerRuntime._build_call_capability(runtime, recovery_ready=True)

    assert status == CallCapabilityStatus(True, True, True, True, True, True, True, True, ("luotianyi",))
    assert status.available is True


@pytest.mark.parametrize(
    "field,mutate",
    [
        ("enabled", lambda runtime: setattr(runtime, "_call_transport_requested", False)),
        ("trusted_host", lambda runtime: setattr(runtime, "_host_context", ServerHostContext())),
        ("provider_ready", lambda runtime: setattr(runtime.realtime_speech_factory, "is_configured", False)),
        (
            "call_tts_ready",
            lambda runtime: setattr(
                runtime.agent_runtime.skills.speaking, "supports_call_audio", lambda _character: False
            ),
        ),
        (
            "summary_ready",
            lambda runtime: setattr(
                runtime.agent_runtime.skills.call_summary, "supports_character", lambda _character: False
            ),
        ),
        ("settlement_ready", lambda runtime: setattr(runtime.call_settlement_coordinator, "is_ready", False)),
        ("stage_binding_ready", lambda runtime: setattr(runtime, "stage_manager", None)),
        ("recovery_ready", lambda runtime: setattr(runtime, "stale_call_recovery", None)),
    ],
)
def test_each_missing_call_capability_fact_fails_closed(field, mutate):
    runtime = ready_runtime()
    mutate(runtime)

    status = ServerRuntime._build_call_capability(runtime, recovery_ready=True)

    assert getattr(status, field) is False
    assert status.available is False


@pytest.mark.parametrize("value", ["false", 1, None, [], {}])
def test_call_transport_rejects_non_boolean_enabled_values(value):
    with pytest.raises(ValueError, match="call_transport.enabled"):
        parse_call_transport_enabled({"call_transport": {"enabled": value}})


def test_call_transport_rejects_non_object_section():
    with pytest.raises(ValueError, match="call_transport must be an object"):
        parse_call_transport_enabled({"call_transport": False})


def test_missing_apology_disables_calls():
    runtime = ready_runtime()
    runtime.agent_runtime.skills.prepared_speech.supports_call_apology = lambda _character: False
    assert not ServerRuntime._build_call_capability(runtime, recovery_ready=True).available
