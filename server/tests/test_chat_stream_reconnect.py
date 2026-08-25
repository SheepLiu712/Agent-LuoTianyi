import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.chat_session.chat_pipeline.chat_stream import ChatStream
from src.chat_session.chat_stream_manager import ChatStreamManager


def test_set_system_runtime_does_not_require_live_websocket_after_disconnect():
    ws_connection = SimpleNamespace(user_name="tester", user_uuid="user-1", websocket=object())
    stream = ChatStream({}, ws_connection, character_id="luotianyi")
    stream.lost_connection()

    stream.set_system_runtime(SimpleNamespace())

    assert stream.system_runtime is not None
    assert stream.ws_connection is None


@pytest.mark.asyncio
async def test_stale_disconnect_does_not_drop_replacement_connection():
    old_connection = SimpleNamespace(user_name="tester", user_uuid="user-1", websocket=object())
    replacement = SimpleNamespace(user_name="tester", user_uuid="user-1", websocket=object())
    replacement_stream = ChatStream({}, old_connection, character_id="luotianyi")
    other_character_stream = ChatStream({}, old_connection, character_id="miku")

    async def already_started():
        return None

    replacement_stream.start_if_needed = already_started
    await replacement_stream.reconnect(replacement)

    manager = ChatStreamManager({}, None, None, None, None)
    manager.user_streams = {
        ("user-1", "luotianyi"): replacement_stream,
        ("user-1", "miku"): other_character_stream,
    }

    manager.ws_lost_connection(old_connection)

    assert replacement_stream.ws_connection is replacement
    assert replacement_stream.connection_lost_time is None
    assert other_character_stream.ws_connection is None
    assert other_character_stream.connection_lost_time is not None


@pytest.mark.asyncio
async def test_replacement_dismisses_old_connection_with_session_replaced():
    """新连接接管聊天流时，旧连接应收到 auth_error(SESSION_REPLACED) 并被关闭。"""
    sent_events: list[dict] = []
    closed: list[bool] = []

    class FakeWebsocket:
        async def send_json(self, event):
            sent_events.append(event)

        async def close(self):
            closed.append(True)

    old_connection = SimpleNamespace(
        user_name="tester", user_uuid="user-1", websocket=FakeWebsocket()
    )
    replacement = SimpleNamespace(
        user_name="tester", user_uuid="user-1", websocket=object()
    )
    stream = ChatStream({}, old_connection, character_id="luotianyi")
    stream.system_runtime = SimpleNamespace(
        websocket_service=SimpleNamespace(_make_event=None)
    )

    def make_event(event_type, payload, reply_to=None):
        return {"type": event_type.value if hasattr(event_type, "value") else event_type,
                "payload": payload}

    stream.system_runtime.websocket_service._make_event = make_event

    async def already_started():
        return None

    stream.start_if_needed = already_started
    await stream.reconnect(replacement)

    assert stream.ws_connection is replacement
    assert len(sent_events) == 1
    assert sent_events[0]["type"] == "auth_error"
    assert sent_events[0]["payload"]["code"] == "SESSION_REPLACED"
    assert closed == [True]
