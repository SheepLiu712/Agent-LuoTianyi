from dataclasses import asdict
from unittest.mock import Mock

import pytest
from cli_client.network.network_client import NetworkClient


@pytest.mark.parametrize("with_extra_fields", [False, True])
def test_get_history_preserves_page_when_server_adds_fields(with_extra_fields):
    expected = [
        {
            "timestamp": "2026-10-08 10:00:00",
            "source": "user",
            "type": "text",
            "content": "你好",
            "uuid": "text-one",
            "duration_ms": None,
            "audio_available": None,
        },
        {
            "timestamp": "2026-10-08 10:00:01",
            "source": "user",
            "type": "audio",
            "content": "[语音消息]",
            "uuid": "audio-one",
            "duration_ms": 1200,
            "audio_available": True,
        },
    ]
    history = [dict(item) for item in expected]
    if with_extra_fields:
        history[0]["future_metadata"] = {"version": 2}
        history[1]["future_flag"] = True
    client = NetworkClient("https://example.invalid")
    client.user_id = "test-user"
    client.message_token = "test-token"
    client.session = Mock()
    client.session.get.return_value.status_code = 200
    client.session.get.return_value.json.return_value = {"history": history, "start_index": 42}

    items, start_index = client.get_history(count=20, end_index=62)

    assert start_index == 42
    assert [asdict(item) for item in items] == expected
    client.session.get.assert_called_once_with(
        "https://example.invalid/history",
        params={"username": "test-user", "count": 20, "end_index": 62},
        headers={"Authorization": "Bearer test-token"},
        verify=True,
        timeout=20,
    )
