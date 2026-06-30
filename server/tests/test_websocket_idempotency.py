import sys
from pathlib import Path

import pytest


server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.system.user_interface.types import WSEventType, WSMessage
from src.system.user_interface.websocket_service import WebSocketConnection, WebSocketService


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


def test_websocket_service_deduplicates_recent_client_message_per_user():
    service = WebSocketService()
    connection = WebSocketConnection(FakeWebSocket(), user_uuid="user-a", user_name="alice")

    assert service.is_duplicate_client_message(connection, _message("msg-1")) is False
    assert service.is_duplicate_client_message(connection, _message("msg-1")) is True
    assert service.is_duplicate_client_message(connection, _message("msg-2")) is False


def test_websocket_service_dedup_cache_is_scoped_by_user():
    service = WebSocketService()
    user_a = WebSocketConnection(FakeWebSocket(), user_uuid="user-a", user_name="alice")
    user_b = WebSocketConnection(FakeWebSocket(), user_uuid="user-b", user_name="bob")

    assert service.is_duplicate_client_message(user_a, _message("same-id")) is False
    assert service.is_duplicate_client_message(user_b, _message("same-id")) is False
    assert service.is_duplicate_client_message(user_a, _message("same-id")) is True
    assert service.is_duplicate_client_message(user_b, _message("same-id")) is True


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
                "received_event_type": WSEventType.USER_TEXT.value,
                "duplicate": True,
            },
            "reply_to": "msg-1",
        }
    ]
