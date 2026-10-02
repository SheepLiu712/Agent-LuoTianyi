"""The authenticated WebSocket ingress acknowledges the three CLI signals."""

import base64
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import WebSocketDisconnect
from PIL import Image

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


async def run_ingress(events, *, negative_ack=True, adapter_config=None):
    socket = Socket(events)
    connection = WebSocketConnection(socket, "user-1", "alice")
    if negative_ack:
        connection.capabilities.add("negative_ack_v1")
    adapter = WebSocketAdapter(adapter_config)
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


@pytest.mark.asyncio
async def test_unconfigured_image_store_reports_stable_media_code():
    sent, stimuli = await run_ingress(
        [event("user_image", {"image_base64": "eA==", "mime_type": "image/png"})]
    )

    assert stimuli == []
    assert sent[0]["payload"] == {
        "ok": False,
        "received_event_type": "user_image",
        "code": "MEDIA_RESOLVER_NOT_CONFIGURED",
        "message": "服务端未配置媒体存储",
        "retryable": False,
    }


@pytest.mark.asyncio
async def test_oversized_image_reports_stable_media_code(tmp_path):
    sent, stimuli = await run_ingress(
        [event("user_image", {"image_base64": "eHh4eA==", "mime_type": "image/png"})],
        adapter_config={"media_store": {"root": str(tmp_path / "media"), "max_bytes": 2}},
    )

    assert stimuli == []
    assert sent[0]["payload"]["code"] == "MEDIA_TOO_LARGE"
    assert sent[0]["payload"]["message"] == "图片过大（上限约 6 MB），请选择更小的图片"
    assert sent[0]["payload"]["retryable"] is False


@pytest.mark.asyncio
async def test_non_image_content_reports_unsupported_type(tmp_path):
    image = BytesIO()
    Image.new("RGB", (1, 1)).save(image, format="PNG")
    sent, stimuli = await run_ingress(
        [
            event(
                "user_image",
                {"image_base64": base64.b64encode(image.getvalue()).decode("ascii"), "mime_type": "image/jpeg"},
            )
        ],
        adapter_config={"media_store": {"root": str(tmp_path / "media")}},
    )

    assert stimuli == []
    assert sent[0]["payload"]["code"] == "MEDIA_UNSUPPORTED_TYPE"
    assert sent[0]["payload"]["message"] == "不支持的图片格式"
    assert sent[0]["payload"]["retryable"] is False
