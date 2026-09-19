import pytest

from src.system.user_interface.types import WSEventType, WSMessage
from src.system.user_interface.websocket_service import WebSocketConnection, WebSocketService


class FakeWebSocket:
    def __init__(self):
        self.sent = []

    async def send_json(self, event):
        self.sent.append(event)


def _message(client_msg_id="msg-1"):
    return WSMessage(
        event_type=WSEventType.USER_TEXT.value,
        payload={"message": "hello"},
        client_msg_id=client_msg_id,
    )


def _connection(*, negative_ack=False):
    connection = WebSocketConnection(FakeWebSocket(), user_uuid="user-1", user_name="alice")
    if negative_ack:
        connection.capabilities.add("negative_ack_v1")
    return connection


@pytest.mark.asyncio
async def test_positive_and_overload_ack_payloads_are_explicit():
    service = WebSocketService()
    connection = _connection(negative_ack=True)
    event = _message()

    await service.send_ack_event(connection, event)
    await service.send_nack_event(
        connection,
        event,
        code="OVERLOADED",
        message="chat ingress queue is full",
        retryable=True,
    )

    assert connection.websocket.sent[0]["payload"]["ok"] is True
    assert connection.websocket.sent[1]["payload"] == {
        "ok": False,
        "received_event_type": WSEventType.USER_TEXT.value,
        "code": "OVERLOADED",
        "message": "chat ingress queue is full",
        "retryable": True,
    }


@pytest.mark.asyncio
async def test_client_without_negative_ack_capability_receives_server_error():
    service = WebSocketService()
    connection = _connection()
    event = _message()

    await service.send_nack_event(
        connection,
        event,
        code="OVERLOADED",
        message="chat ingress queue is full",
        retryable=True,
    )

    assert connection.websocket.sent[0]["type"] == WSEventType.SERVER_ERROR.value
    assert "ok" not in connection.websocket.sent[0]["payload"]
