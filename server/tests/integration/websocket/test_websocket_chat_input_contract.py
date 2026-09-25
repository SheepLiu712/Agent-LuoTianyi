"""The authenticated WebSocket ingress acknowledges the three CLI signals."""

from types import SimpleNamespace

import pytest
from fastapi import WebSocketDisconnect

import src.domain.agent as d
from src.adapter.websocket import WebSocketAdapter
from src.web.websocket import WSEventType
from src.web.websocket.endpoint import _receive_events
from src.web.websocket.service import WebSocketConnection, WebSocketService


class Socket:
    def __init__(self, events):
        self.events = list(events)
        self.sent = []

    async def receive_json(self):
        if self.events:
            return self.events.pop(0)
        raise WebSocketDisconnect()

    async def send_json(self, event):
        self.sent.append(event)


class Stage:
    def __init__(self):
        self.interaction_id = "interaction"
        self.user_id = "user-1"
        self.character_id = "luotianyi"
        self.stimulus_input_sink = self
        self.stimuli = []

    def can_accept(self, stimulus):
        return True

    def submit(self, stimulus):
        self.stimuli.append(stimulus)
        return True

    async def connection_changed(self, state):
        pass


def event(event_type, payload, client_msg_id="chat-1"):
    return {"type": event_type, "client_msg_id": client_msg_id, "payload": payload}


async def run_ingress(events, *, negative_ack=True):
    socket = Socket(events)
    connection = WebSocketConnection(socket, "user-1", "alice")
    if negative_ack:
        connection.capabilities.add("negative_ack_v1")
    adapter = WebSocketAdapter()
    stage = Stage()
    await adapter.bind(stage, connection)
    runtime = SimpleNamespace(
        websocket_service=WebSocketService(),
        chat_adapter=adapter,
        client_llm_executor=SimpleNamespace(),
    )
    try:
        with pytest.raises(WebSocketDisconnect):
            await _receive_events(runtime, connection)
        return socket.sent, stage.stimuli
    finally:
        await adapter.disconnect(stage)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event_type", "payload", "stimulus_type"),
    [
        ("user_touch", {"touchArea": ["head"]}, d.TouchInteraction),
        ("user_image_selecting", {}, d.ImageSelectionOpened),
        ("user_image_selecting_cancel", {}, d.ImageSelectionClosed),
    ],
)
async def test_cli_signal_is_acknowledged_and_submitted_once(event_type, payload, stimulus_type):
    incoming = event(event_type, payload)
    sent, stimuli = await run_ingress([incoming, incoming])

    assert len(stimuli) == 1
    assert isinstance(stimuli[0], stimulus_type)
    assert stimuli[0].user_id == "user-1"
    assert stimuli[0].ephemeral is True
    assert [item["type"] for item in sent] == ["server_ack", "server_ack"]
    assert [item["reply_to"] for item in sent] == ["chat-1", "chat-1"]
    assert sent[0]["payload"] == {"ok": True, "received_event_type": event_type}
    assert sent[1]["payload"]["duplicate"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event_type", "payload"),
    [
        ("user_touch", {}),
        ("user_image_selecting", []),
        ("user_image_selecting_cancel", "invalid"),
    ],
)
@pytest.mark.parametrize("negative_ack", [True, False])
async def test_invalid_cli_signal_reports_bad_message(event_type, payload, negative_ack):
    sent, stimuli = await run_ingress([event(event_type, payload)], negative_ack=negative_ack)

    assert stimuli == []
    assert len(sent) == 1
    assert sent[0]["type"] == (
        WSEventType.SERVER_ACK.value if negative_ack else WSEventType.SERVER_ERROR.value
    )
    assert sent[0]["reply_to"] == "chat-1"
    assert sent[0]["payload"]["code"] == "BAD_MESSAGE"
    assert sent[0]["payload"]["received_event_type"] == event_type


@pytest.mark.asyncio
async def test_unknown_event_does_not_enter_chat_ingress():
    sent, stimuli = await run_ingress([event("client_diagnostic", {"value": 1})])
    assert sent == []
    assert stimuli == []
