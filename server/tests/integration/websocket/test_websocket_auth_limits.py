import asyncio
from types import SimpleNamespace

import pytest

from src.system.user_interface.types import WSEventType, WSMessage
from src.system.user_interface.websocket_service import WebSocketConnection, WebSocketService


class FakeWebSocket:
    def __init__(self):
        self.sent = []
        self.close_codes = []

    async def send_json(self, event):
        self.sent.append(event)

    async def close(self, code):
        self.close_codes.append(code)

    async def accept(self):
        return None


@pytest.mark.asyncio
async def test_websocket_auth_times_out_and_closes_connection(monkeypatch):
    service = WebSocketService()
    websocket = FakeWebSocket()
    connection = WebSocketConnection(websocket, user_uuid=None, user_name=None)

    async def never_receive(_connection):
        await asyncio.Event().wait()

    monkeypatch.setattr(service, "try_recv_client_msg", never_receive)

    result = await connection.auth(service, object(), timeout_seconds=0.01)

    assert result is False
    assert websocket.close_codes == [1008]
    assert websocket.sent[-1]["payload"]["code"] == "AUTH_TIMEOUT"


@pytest.mark.asyncio
async def test_websocket_auth_counts_non_auth_frames(monkeypatch):
    service = WebSocketService()
    websocket = FakeWebSocket()
    connection = WebSocketConnection(websocket, user_uuid=None, user_name=None)
    attempts = 0

    async def receive_non_auth(_connection):
        nonlocal attempts
        attempts += 1
        return WSMessage(event_type=WSEventType.HB_PING.value, payload={})

    monkeypatch.setattr(service, "try_recv_client_msg", receive_non_auth)

    result = await connection.auth(service, object(), timeout_seconds=1, max_attempts=3)

    assert result is False
    assert attempts == 3
    assert websocket.close_codes == [1008]
    assert websocket.sent[-1]["payload"]["code"] == "AUTH_ATTEMPTS_EXCEEDED"


@pytest.mark.asyncio
async def test_websocket_auth_succeeds_within_attempt_limit(monkeypatch):
    service = WebSocketService()
    websocket = FakeWebSocket()
    connection = WebSocketConnection(websocket, user_uuid=None, user_name=None)
    auth_event = WSMessage(
        event_type=WSEventType.USER_AUTH.value,
        payload={"username": "alice", "token": "valid-token"},
    )

    async def receive_auth(_connection):
        return auth_event

    async def accept_auth(_connection, _database, _event):
        connection.set_user("user-1", "alice")
        return True

    monkeypatch.setattr(service, "try_recv_client_msg", receive_auth)
    monkeypatch.setattr(service, "handle_auth_event", accept_auth)

    result = await connection.auth(service, object(), timeout_seconds=1, max_attempts=2)

    assert result is True
    assert connection.user_uuid == "user-1"
    assert websocket.close_codes == []


@pytest.mark.asyncio
async def test_auth_negotiates_negative_ack_capability():
    service = WebSocketService()
    websocket = FakeWebSocket()
    connection = WebSocketConnection(websocket, user_uuid=None, user_name=None)
    database = SimpleNamespace(
        credential_service=SimpleNamespace(
            check_message_token=lambda _username, _token: (True, "user-1"),
        ),
    )
    event = WSMessage(
        event_type=WSEventType.USER_AUTH.value,
        payload={
            "username": "alice",
            "token": "valid-token",
            "capabilities": ["negative_ack_v1", "unknown"],
        },
        client_msg_id="auth-1",
    )

    assert await service.handle_auth_event(connection, database, event) is True
    assert connection.capabilities == {"negative_ack_v1"}
    assert websocket.sent[-1]["payload"]["capabilities"] == ["negative_ack_v1"]


@pytest.mark.asyncio
async def test_chat_route_does_not_register_stream_after_auth_rejection(monkeypatch):
    import server_main

    registrations = []
    runtime = SimpleNamespace(
        websocket_service=SimpleNamespace(
            send_system_ready_event=lambda _websocket: asyncio.sleep(0),
        ),
        gcsm=SimpleNamespace(
            get_or_register_chat_stream=lambda *_args, **_kwargs: registrations.append(True),
        ),
        database_manager=object(),
    )
    monkeypatch.setattr(
        server_main,
        "get_admin_shell",
        lambda: SimpleNamespace(runtime_supervisor=SimpleNamespace(runtime=runtime)),
    )

    async def reject_auth(self, _service, _database):
        return False

    monkeypatch.setattr(WebSocketConnection, "auth", reject_auth)

    await server_main.chat_ws(FakeWebSocket())

    assert registrations == []
