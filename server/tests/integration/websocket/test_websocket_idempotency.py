import sys
from pathlib import Path

import pytest


server_root = str(Path(__file__).resolve().parents[3])
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.web.websocket import WSEventType, WSMessage
from src.web.websocket.service import WebSocketConnection, WebSocketService
from src.adapter.websocket import WebSocketAdapter


class FakeWebSocket:
    def __init__(self):
        self.sent = []

    async def send_json(self, event):
        self.sent.append(event)


def _message(client_msg_id: str) -> WSMessage:
    return WSMessage(
        event_type=WSEventType.USER_TEXT.value,
        payload={"text": "你好"},
        client_msg_id=client_msg_id,
    )


def test_websocket_adapter_deduplicates_recent_client_message_per_user():
    adapter = WebSocketAdapter()
    connection = WebSocketConnection(FakeWebSocket(), user_uuid="user-a", user_name="alice")

    assert adapter.is_duplicate_client_message(connection, _message("msg-1")) is False
    assert adapter.is_duplicate_client_message(connection, _message("msg-1")) is False
    assert adapter.mark_client_message_accepted(connection, _message("msg-1")) is True
    assert adapter.is_duplicate_client_message(connection, _message("msg-1")) is True
    assert adapter.is_duplicate_client_message(connection, _message("msg-2")) is False


def test_websocket_adapter_dedup_cache_is_scoped_by_user():
    adapter = WebSocketAdapter()
    user_a = WebSocketConnection(FakeWebSocket(), user_uuid="user-a", user_name="alice")
    user_b = WebSocketConnection(FakeWebSocket(), user_uuid="user-b", user_name="bob")

    assert adapter.mark_client_message_accepted(user_a, _message("same-id")) is True
    assert adapter.mark_client_message_accepted(user_b, _message("same-id")) is True
    assert adapter.is_duplicate_client_message(user_a, _message("same-id")) is True
    assert adapter.is_duplicate_client_message(user_b, _message("same-id")) is True


@pytest.mark.asyncio
async def test_duplicate_ack_marks_duplicate_payload():
    service = WebSocketService()
    websocket = FakeWebSocket()
    connection = WebSocketConnection(websocket, user_uuid="user-a", user_name="alice")

    await service.send_duplicate_ack_event(connection, _message("msg-1"))

    assert websocket.sent == [
        {
            "type": WSEventType.SERVER_ACK.value,
            "ts": websocket.sent[0]["ts"],
            "payload": {
                "ok": True,
                "received_event_type": WSEventType.USER_TEXT.value,
                "duplicate": True,
            },
            "reply_to": "msg-1",
        }
    ]
