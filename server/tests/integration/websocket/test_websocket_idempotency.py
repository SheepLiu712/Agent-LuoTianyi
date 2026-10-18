import json

import pytest
from support.chat_connection import StubChatConnection

from src.adapter.websocket.chat import WebSocketAdapter
from src.adapter.websocket.chat._messages import _WSMessage


class FakeWebSocket:
    def __init__(self):
        self.sent = []

    async def send_json(self, event):
        self.sent.append(event)


def _message(client_msg_id: str) -> _WSMessage:
    return _WSMessage(
        event_type="user_text",
        payload={"text": "你好"},
        client_msg_id=client_msg_id,
    )


def test_websocket_adapter_deduplicates_recent_client_message_per_user():
    adapter = WebSocketAdapter()
    connection = StubChatConnection(FakeWebSocket(), user_uuid="user-a", user_name="alice")

    assert adapter._is_duplicate_client_message(connection, _message("msg-1")) is False
    assert adapter._is_duplicate_client_message(connection, _message("msg-1")) is False
    assert adapter._mark_client_message_accepted(connection, _message("msg-1")) is True
    assert adapter._is_duplicate_client_message(connection, _message("msg-1")) is True
    assert adapter._is_duplicate_client_message(connection, _message("msg-2")) is False


def test_websocket_adapter_dedup_cache_is_scoped_by_user():
    adapter = WebSocketAdapter()
    user_a = StubChatConnection(FakeWebSocket(), user_uuid="user-a", user_name="alice")
    user_b = StubChatConnection(FakeWebSocket(), user_uuid="user-b", user_name="bob")

    assert adapter._mark_client_message_accepted(user_a, _message("same-id")) is True
    assert adapter._mark_client_message_accepted(user_b, _message("same-id")) is True
    assert adapter._is_duplicate_client_message(user_a, _message("same-id")) is True
    assert adapter._is_duplicate_client_message(user_b, _message("same-id")) is True


@pytest.mark.asyncio
async def test_duplicate_ack_marks_duplicate_payload():
    from tests.integration.websocket.test_adapter_network_boundary import _chat

    adapter, connection, stages = await _chat()
    raw = json.dumps({"type": "user_text", "client_msg_id": "one", "payload": {"message": "hello"}})
    try:
        await adapter.receive(connection, raw)
        original = await adapter.next_output(connection)
        adapter.complete_output(connection, original.delivery_id)
        await adapter.receive(connection, raw)
        duplicate = await adapter.next_output(connection)
        assert json.loads(duplicate.message)["payload"] == {
            "ok": True,
            "received_event_type": "user_text",
            "duplicate": True,
        }
        assert len(stages.stage.stimuli) == 1
    finally:
        await adapter.close()
