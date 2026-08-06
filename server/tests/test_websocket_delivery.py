from types import SimpleNamespace

import pytest

from src.agent_runtime.character_registry import CharacterRegistry
from src.system.user_interface.types import WSEventType, WSMessage
from src.system.user_interface.websocket_service import (
    ChatEventAcceptance,
    WebSocketConnection,
    WebSocketService,
)


class FakeWebSocket:
    def __init__(self):
        self.sent = []

    async def send_json(self, event):
        self.sent.append(event)


class CapacityStream:
    def __init__(self, capacity: int, *, character_id="luotianyi", system_runtime=None):
        self.capacity = capacity
        self.events = []
        self.character_id = character_id
        self.system_runtime = system_runtime

    def try_feed_event(self, event):
        if len(self.events) >= self.capacity:
            return False
        self.events.append(event)
        return True


def _message(client_msg_id="msg-1"):
    return WSMessage(
        event_type=WSEventType.USER_TEXT.value,
        payload={"message": "hello"},
        client_msg_id=client_msg_id,
    )


def _connection(*, negative_ack=False):
    connection = WebSocketConnection(
        FakeWebSocket(),
        user_uuid="user-1",
        user_name="alice",
    )
    if negative_ack:
        connection.capabilities.add("negative_ack_v1")
    return connection


def test_successful_acceptance_is_marked_only_after_enqueue():
    service = WebSocketService()
    connection = _connection()
    stream = CapacityStream(capacity=1)
    event = _message()

    assert service.try_accept_chat_event(connection, event, stream) == ChatEventAcceptance.ACCEPTED
    assert len(stream.events) == 1
    assert service.try_accept_chat_event(connection, event, stream) == ChatEventAcceptance.DUPLICATE
    assert len(stream.events) == 1


def test_overload_is_not_marked_and_same_id_can_retry():
    service = WebSocketService()
    connection = _connection()
    stream = CapacityStream(capacity=0)
    event = _message()

    assert service.try_accept_chat_event(connection, event, stream) == ChatEventAcceptance.OVERLOADED
    assert service.is_duplicate_client_message(connection, event) is False

    stream.capacity = 1
    assert service.try_accept_chat_event(connection, event, stream) == ChatEventAcceptance.ACCEPTED
    assert len(stream.events) == 1


def test_bad_message_is_not_marked(monkeypatch):
    service = WebSocketService()
    connection = _connection()
    event = _message()

    def fail_conversion(*_args, **_kwargs):
        raise ValueError("bad payload")

    monkeypatch.setattr(service, "convert_to_chat_input_event", fail_conversion)

    assert service.try_accept_chat_event(connection, event, CapacityStream(1)) == ChatEventAcceptance.BAD_MESSAGE
    assert service.is_duplicate_client_message(connection, event) is False


def test_missing_or_oversized_client_message_id_is_rejected():
    service = WebSocketService()
    connection = _connection()
    stream = CapacityStream(1)

    assert service.try_accept_chat_event(connection, _message(None), stream) == ChatEventAcceptance.BAD_MESSAGE
    assert service.try_accept_chat_event(connection, _message("x" * 129), stream) == ChatEventAcceptance.BAD_MESSAGE
    assert stream.events == []


@pytest.mark.parametrize(
    ("event_type", "payload"),
    [
        (WSEventType.USER_TEXT.value, {}),
        (WSEventType.USER_TEXT.value, {"message": "   "}),
        (WSEventType.USER_IMAGE.value, {"image_base64": "%%%", "mime_type": "image/png"}),
        (WSEventType.USER_IMAGE.value, {"image_base64": "aGVsbG8="}),
        (WSEventType.USER_TYPING.value, {}),
        (WSEventType.USER_TYPING.value, {"text_length": True}),
        (WSEventType.USER_TOUCH.value, {}),
        (WSEventType.USER_IMAGE_SELECTING.value, []),
    ],
)
def test_real_invalid_payloads_are_rejected_before_mark(event_type, payload):
    service = WebSocketService()
    connection = _connection()
    stream = CapacityStream(1)
    event = WSMessage(event_type=event_type, payload=payload, client_msg_id="bad-1")

    assert service.try_accept_chat_event(connection, event, stream) == ChatEventAcceptance.BAD_MESSAGE
    assert service.is_duplicate_client_message(connection, event) is False
    assert stream.events == []


def test_corrected_payload_can_reuse_id_after_schema_rejection():
    service = WebSocketService()
    connection = _connection()
    stream = CapacityStream(1)
    event = WSMessage(
        event_type=WSEventType.USER_TEXT.value,
        payload={"message": ""},
        client_msg_id="corrected-1",
    )

    assert service.try_accept_chat_event(connection, event, stream) == ChatEventAcceptance.BAD_MESSAGE
    event.payload = {"message": "hello"}
    assert service.try_accept_chat_event(connection, event, stream) == ChatEventAcceptance.ACCEPTED


def test_default_target_uses_stream_character_and_invalid_targets_fail_fast():
    registry = CharacterRegistry(
        {
            "characters": {
                "miku": {"enabled": True, "default_target": True},
                "disabled": {"enabled": False},
            }
        }
    )
    runtime = SimpleNamespace(
        agent_runtime=SimpleNamespace(character_registry=registry),
    )
    service = WebSocketService()
    connection = _connection()
    stream = CapacityStream(3, character_id="miku", system_runtime=runtime)

    assert service.try_accept_chat_event(connection, _message("default-1"), stream) == ChatEventAcceptance.ACCEPTED
    assert stream.events[0].payload["target_character_ids"] == ["miku"]

    for target in ("unknown", "disabled"):
        event = WSMessage(
            event_type=WSEventType.USER_TEXT.value,
            payload={"message": "hello", "target_character_id": target},
            client_msg_id=f"target-{target}",
        )
        assert service.try_accept_chat_event(connection, event, stream) == ChatEventAcceptance.BAD_MESSAGE
        assert service.is_duplicate_client_message(connection, event) is False


def test_single_string_target_is_normalized_before_registry_validation():
    registry = CharacterRegistry(
        {"characters": {"miku": {"enabled": True, "default_target": True}}}
    )
    runtime = SimpleNamespace(
        agent_runtime=SimpleNamespace(character_registry=registry),
    )
    service = WebSocketService()
    connection = _connection()
    stream = CapacityStream(1, character_id="miku", system_runtime=runtime)
    event = WSMessage(
        event_type=WSEventType.USER_TEXT.value,
        payload={"message": "hello", "target_character_ids": "miku"},
        client_msg_id="string-target-1",
    )

    assert service.try_accept_chat_event(connection, event, stream) == ChatEventAcceptance.ACCEPTED
    assert stream.events[0].payload["target_character_ids"] == ["miku"]


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
async def test_legacy_client_receives_server_error_instead_of_negative_ack():
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
