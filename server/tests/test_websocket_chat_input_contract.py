from types import SimpleNamespace

import pytest
from fastapi import WebSocketDisconnect

import server_main
from src.domain.chat import ChatInputEventType
from src.domain.stimulus import SourceChannel, StimulusModality
from src.system.user_interface.types import WSEventType
from src.system.user_interface.websocket_service import WebSocketService


class FakeWebSocket:
    def __init__(self, received):
        self.received = list(received)
        self.sent = []

    async def accept(self):
        return None

    async def receive_json(self):
        if self.received:
            return self.received.pop(0)
        raise WebSocketDisconnect()

    async def send_json(self, event):
        self.sent.append(event)


class RecordingWebSocketService(WebSocketService):
    def __init__(self):
        super().__init__()
        self.stimuli = []

    def convert_to_stimulus(self, event, sender_user_id=None, default_character_id="luotianyi"):
        stimulus = super().convert_to_stimulus(
            event,
            sender_user_id=sender_user_id,
            default_character_id=default_character_id,
        )
        self.stimuli.append(stimulus)
        return stimulus


class RecordingChatStream:
    character_id = "luotianyi"
    system_runtime = None

    def __init__(self):
        self.events = []

    def try_feed_event(self, event):
        self.events.append(event)
        return True


def _auth_event(*, negative_ack=True):
    capabilities = ["negative_ack_v1"] if negative_ack else []
    return {
        "type": WSEventType.USER_AUTH.value,
        "client_msg_id": "auth-1",
        "payload": {
            "username": "alice",
            "token": "valid-token",
            "capabilities": capabilities,
        },
    }


def _chat_event(event_type, payload, client_msg_id="chat-1"):
    return {
        "type": event_type,
        "client_msg_id": client_msg_id,
        "ts": 1_700_000_000_000,
        "payload": payload,
    }


async def _run_session(monkeypatch, *events, negative_ack=True):
    websocket = FakeWebSocket([_auth_event(negative_ack=negative_ack), *events])
    service = RecordingWebSocketService()
    stream = RecordingChatStream()
    runtime = SimpleNamespace(
        websocket_service=service,
        database_manager=SimpleNamespace(
            credential_service=SimpleNamespace(
                check_message_token=lambda username, token: (
                    username == "alice" and token == "valid-token",
                    "user-1",
                ),
            ),
        ),
        gcsm=SimpleNamespace(
            get_or_register_chat_stream=lambda *_args, **_kwargs: _async_value(stream),
            ws_lost_connection=lambda _connection: None,
        ),
        client_llm_executor=SimpleNamespace(clear_user=lambda *_args: None),
    )
    monkeypatch.setattr(
        server_main,
        "get_admin_shell",
        lambda: SimpleNamespace(runtime_supervisor=SimpleNamespace(runtime=runtime)),
    )

    await server_main.chat_ws(websocket)
    return websocket, service, stream


async def _async_value(value):
    return value


def _events_of_type(websocket, event_type):
    return [event for event in websocket.sent if event["type"] == event_type]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event_type", "payload", "modality", "chat_event_type"),
    [
        (
            WSEventType.USER_TOUCH.value,
            {"touchArea": ["head"], "click_frequency": {"count_10s": 1}},
            StimulusModality.TOUCH,
            ChatInputEventType.USER_TOUCH,
        ),
        (
            WSEventType.USER_IMAGE_SELECTING.value,
            {},
            StimulusModality.IMAGE_SELECTING,
            ChatInputEventType.USER_IMAGE_SELECTING,
        ),
        (
            WSEventType.USER_IMAGE_SELECTING_CANCEL.value,
            {},
            StimulusModality.IMAGE_SELECTING_CANCEL,
            ChatInputEventType.USER_IMAGE_SELECTING_CANCEL,
        ),
    ],
)
async def test_authenticated_chat_input_is_acked_and_enters_ingress_as_stimulus(
    monkeypatch,
    event_type,
    payload,
    modality,
    chat_event_type,
):
    client_msg_id = f"{event_type}-1"
    websocket, service, stream = await _run_session(
        monkeypatch,
        _chat_event(event_type, payload, client_msg_id),
    )

    ack = _events_of_type(websocket, WSEventType.SERVER_ACK.value)[0]
    assert ack["payload"]["ok"] is True
    assert ack["payload"]["received_event_type"] == event_type
    assert ack["reply_to"] == client_msg_id

    assert len(service.stimuli) == 1
    stimulus = service.stimuli[0]
    assert stimulus.source_channel == SourceChannel.WEBSOCKET
    assert stimulus.modality == modality
    assert stimulus.sender_user_id == "user-1"
    assert stimulus.client_msg_id == client_msg_id
    assert stimulus.raw_event_type == event_type

    assert len(stream.events) == 1
    assert stream.events[0].event_type == chat_event_type
    assert stream.events[0].client_msg_id == client_msg_id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event_type", "payload"),
    [
        (WSEventType.USER_TOUCH.value, {"touchArea": ["head"]}),
        (WSEventType.USER_IMAGE_SELECTING.value, {}),
        (WSEventType.USER_IMAGE_SELECTING_CANCEL.value, {}),
    ],
)
async def test_duplicate_chat_input_keeps_original_reply_to(monkeypatch, event_type, payload):
    original = _chat_event(event_type, payload, "same-id")
    websocket, _service, stream = await _run_session(monkeypatch, original, dict(original))

    acks = _events_of_type(websocket, WSEventType.SERVER_ACK.value)
    assert len(acks) == 2
    assert acks[1]["payload"]["ok"] is True
    assert acks[1]["payload"]["duplicate"] is True
    assert acks[1]["payload"]["received_event_type"] == event_type
    assert acks[1]["reply_to"] == "same-id"
    assert len(stream.events) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event_type", "invalid_payload"),
    [
        (WSEventType.USER_TOUCH.value, {}),
        (WSEventType.USER_IMAGE_SELECTING.value, []),
        (WSEventType.USER_IMAGE_SELECTING_CANCEL.value, "invalid"),
    ],
)
@pytest.mark.parametrize("negative_ack", [True, False])
async def test_invalid_payload_returns_bad_message_for_negotiated_and_legacy_clients(
    monkeypatch,
    event_type,
    invalid_payload,
    negative_ack,
):
    websocket, service, stream = await _run_session(
        monkeypatch,
        _chat_event(event_type, invalid_payload, "bad-1"),
        negative_ack=negative_ack,
    )

    response = websocket.sent[-1]
    assert response["type"] == (
        WSEventType.SERVER_ACK.value if negative_ack else WSEventType.SERVER_ERROR.value
    )
    assert response["payload"]["code"] == "BAD_MESSAGE"
    assert response["payload"]["received_event_type"] == event_type
    assert response["reply_to"] == "bad-1"
    if negative_ack:
        assert response["payload"]["ok"] is False
    else:
        assert "ok" not in response["payload"]
    assert service.stimuli == []
    assert stream.events == []


@pytest.mark.asyncio
async def test_unrecognized_non_chat_event_is_silently_ignored(monkeypatch):
    websocket, service, stream = await _run_session(
        monkeypatch,
        _chat_event("client_diagnostic", {"value": 1}, "unknown-1"),
    )

    assert [event["type"] for event in websocket.sent] == [
        WSEventType.SYSTEM_READY.value,
        WSEventType.AUTH_OK.value,
    ]
    assert service.stimuli == []
    assert stream.events == []
