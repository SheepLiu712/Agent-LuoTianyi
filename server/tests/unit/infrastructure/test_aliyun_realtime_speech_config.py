import math
from uuid import uuid4

import pytest

from src.infrastructure.models.realtime_speech import (
    AliyunRealtimeSpeechConfig,
    AliyunRealtimeSpeechSessionFactory,
    RealtimeSpeechConfigError,
    RealtimeSpeechUnavailable,
)


def test_workspace_config_builds_explicit_model_url_without_exposing_secret():
    config = AliyunRealtimeSpeechConfig(api_key="secret-value", workspace_id="workspace", model="chosen-model")

    assert config.websocket_url == (
        "wss://workspace.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime?model=chosen-model"
    )
    assert "secret-value" not in repr(config)


def test_custom_endpoint_is_controlled_and_model_query_is_replaced():
    config = AliyunRealtimeSpeechConfig(
        api_key="key", model="configured-model", endpoint="wss://provider.example/realtime?tenant=one&model=old"
    )

    assert config.websocket_url == "wss://provider.example/realtime?tenant=one&model=configured-model"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("enabled", 1),
        ("enabled", "true"),
        ("api_key", object()),
        ("model", 7),
        ("workspace_id", object()),
        ("connect_timeout_seconds", True),
        ("session_timeout_seconds", math.nan),
        ("close_timeout_seconds", math.inf),
        ("cleanup_timeout_seconds", -1.0),
        ("write_queue_size", "4"),
        ("event_queue_size", 2.0),
        ("max_audio_frame_bytes", True),
    ],
)
def test_enabled_provider_config_rejects_bad_types_without_coercion(field, value):
    config = {"enabled": True, "api_key": "key", "model": "model", "workspace_id": "workspace"}
    config[field] = value

    with pytest.raises(RealtimeSpeechConfigError) as exc_info:
        AliyunRealtimeSpeechSessionFactory.from_mapping(config)

    assert "not-echoed" not in str(exc_info.value)
    assert repr(value) not in str(exc_info.value)


def test_custom_endpoint_requires_transport_security():
    config = AliyunRealtimeSpeechConfig(
        api_key="key", model="configured-model", endpoint="ws://provider.example/realtime"
    )

    with pytest.raises(RealtimeSpeechConfigError, match="secure wss"):
        _ = config.websocket_url


@pytest.mark.asyncio
async def test_factory_distinguishes_disabled_capability_from_invalid_enabled_config():
    disabled = AliyunRealtimeSpeechSessionFactory.from_mapping({"enabled": False})
    with pytest.raises(RealtimeSpeechUnavailable):
        await disabled.create(uuid4())

    with pytest.raises(RealtimeSpeechConfigError, match="model"):
        AliyunRealtimeSpeechSessionFactory.from_mapping({"enabled": True, "api_key": "not-echoed"})
