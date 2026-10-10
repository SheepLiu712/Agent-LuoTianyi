from types import SimpleNamespace

import pytest

from src.adapter.websocket.call_v1 import parse_call_transport_enabled
from src.server_runtime import ServerRuntime


@pytest.mark.parametrize("config", [{}, {"call_transport": {}}, {"call_transport": {"enabled": False}}])
def test_call_transport_defaults_to_disabled(config):
    assert parse_call_transport_enabled(config) is False


def test_call_transport_accepts_explicit_boolean_request_but_runtime_remains_unavailable():
    runtime = SimpleNamespace(
        _call_transport_requested=parse_call_transport_enabled({"call_transport": {"enabled": True}})
    )

    assert runtime._call_transport_requested is True
    assert ServerRuntime.call_transport_available.__get__(runtime, ServerRuntime) is False


@pytest.mark.parametrize("value", ["false", 1, None, [], {}])
def test_call_transport_rejects_non_boolean_enabled_values(value):
    with pytest.raises(ValueError, match="call_transport.enabled"):
        parse_call_transport_enabled({"call_transport": {"enabled": value}})


def test_call_transport_rejects_non_object_section():
    with pytest.raises(ValueError, match="call_transport must be an object"):
        parse_call_transport_enabled({"call_transport": False})
