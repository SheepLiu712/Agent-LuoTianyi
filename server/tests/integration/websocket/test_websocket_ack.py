import json

import pytest

from src.adapter.websocket.chat import WebSocketAdapter
from tests.integration.websocket.test_adapter_network_boundary import _Manager


@pytest.mark.asyncio
@pytest.mark.parametrize("negative_ack", [False, True])
async def test_raw_input_ack_and_overload_respect_negotiated_capability(negative_ack):
    adapter = WebSocketAdapter()
    manager = _Manager()
    adapter.initialize(manager)
    connection = await adapter.open(
        user_id="user",
        connection_id=object(),
        capabilities=frozenset({"negative_ack_v1"}) if negative_ack else frozenset(),
    )
    ready = await adapter.next_output(connection)
    adapter.complete_output(connection, ready.delivery_id)
    message = {"type": "user_text", "client_msg_id": "one", "payload": {"message": "hello"}}
    try:
        await adapter.receive(connection, json.dumps(message))
        accepted = await adapter.next_output(connection)
        assert json.loads(accepted.message)["payload"]["ok"] is True
        adapter.complete_output(connection, accepted.delivery_id)
        manager.stage.available = False
        message["client_msg_id"] = "two"
        await adapter.receive(connection, json.dumps(message))
        rejected = await adapter.next_output(connection)
        body = json.loads(rejected.message)
        assert body["type"] == ("server_ack" if negative_ack else "error")
        assert body["payload"]["code"] == "OVERLOADED"
        assert body["payload"]["retryable"] is True
        assert body["reply_to"] == "two"
        if negative_ack:
            assert body["payload"]["ok"] is False
        else:
            assert "ok" not in body["payload"]
    finally:
        await adapter.close()
