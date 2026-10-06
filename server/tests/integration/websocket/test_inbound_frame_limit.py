"""入站帧上限必须覆盖真实图片尺寸，否则既有图片发送功能会被拒收。

期望值一律取自**媒体库自身的限额**（`PermanentMediaStore.max_encoded_bytes`），
而不是 `service.py` 里的同名常量，否则测试会拿被测常量给自己当期望、对缺陷恒真。
"""

import pytest
from fastapi import WebSocketDisconnect

from src.infrastructure.media import PermanentMediaStore
from src.web.websocket.service import (
    INBOUND_FRAME_ENVELOPE_BYTES,
    WebSocketConnection,
    WebSocketService,
    resolve_max_inbound_frame_bytes,
)


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


def _image_event(base64_length: int) -> dict:
    return {
        "type": "user_image",
        "client_msg_id": "image-1",
        "payload": {"image_base64": "A" * base64_length, "mime_type": "image/jpeg"},
    }


def _media_store(tmp_path, **overrides) -> PermanentMediaStore:
    return PermanentMediaStore({"root": str(tmp_path / "media"), **overrides})


def test_default_limit_covers_the_image_path_limit(tmp_path):
    """默认帧上限必须覆盖媒体库允许的 base64 图片长度（默认 8 MiB）加信封。"""
    image_limit = _media_store(tmp_path).max_encoded_bytes

    assert WebSocketService().max_inbound_frame_bytes >= image_limit + INBOUND_FRAME_ENVELOPE_BYTES
    assert resolve_max_inbound_frame_bytes({}) >= image_limit + INBOUND_FRAME_ENVELOPE_BYTES


def test_configured_media_limit_drives_the_frame_limit(tmp_path):
    """帧上限必须跟随生产 config 里的同一个 max_encoded_bytes（不是独立常量）。"""
    media_limit = 12 * 1024 * 1024
    image_limit = _media_store(tmp_path, max_encoded_bytes=media_limit).max_encoded_bytes

    assert image_limit == media_limit
    assert resolve_max_inbound_frame_bytes({"max_encoded_bytes": media_limit}) == (
        image_limit + INBOUND_FRAME_ENVELOPE_BYTES
    )


@pytest.mark.asyncio
async def test_default_limit_accepts_a_full_size_image_frame(tmp_path):
    """媒体库允许的最大 base64 图片必须能整帧通过（历史回归：128 KiB 上限会拒收真实照片）。"""
    image_limit = _media_store(tmp_path).max_encoded_bytes
    socket = Socket([_image_event(image_limit)])
    connection = WebSocketConnection(socket, "user-1", "user-1")

    event = await WebSocketService().try_recv_client_msg(connection)

    assert event is not None
    assert event.event_type == "user_image"
    assert socket.sent == []


@pytest.mark.asyncio
async def test_configured_media_limit_raises_frame_limit(tmp_path):
    media_limit = 12 * 1024 * 1024
    socket = Socket([_image_event(_media_store(tmp_path, max_encoded_bytes=media_limit).max_encoded_bytes)])
    connection = WebSocketConnection(socket, "user-1", "user-1")
    service = WebSocketService(
        max_inbound_frame_bytes=resolve_max_inbound_frame_bytes({"max_encoded_bytes": media_limit})
    )

    event = await service.try_recv_client_msg(connection)

    assert event is not None
    assert socket.sent == []
