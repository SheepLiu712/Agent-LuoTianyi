import asyncio
from types import SimpleNamespace

import pytest

from src.web.websocket.service import WebSocketConnection, WebSocketService


class FakeWebSocket:
    def __init__(self, messages=()):
        self.sent = []
        self.close_codes = []
        self.messages = iter(messages)

    async def receive_json(self):
        event = next(self.messages)
        if isinstance(event, Exception):
            raise event
        return event

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

    monkeypatch.setattr(service, "_receive_auth_message", never_receive)

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
        return dict(type="hb_ping", payload={})

    monkeypatch.setattr(service, "_receive_auth_message", receive_non_auth)

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
    auth_event = dict(
        type="user_auth",
        payload={"username": "alice", "token": "valid-token"},
    )

    async def receive_auth(_connection):
        return auth_event

    async def accept_auth(_connection, _database, _event):
        connection.set_user("user-1", "alice")
        return True

    monkeypatch.setattr(service, "_receive_auth_message", receive_auth)
    monkeypatch.setattr(service, "_authenticate_message", accept_auth)

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
    event = dict(
        type="user_auth",
        payload={
            "username": "alice",
            "token": "valid-token",
            "capabilities": ["negative_ack_v1", "unknown"],
        },
        client_msg_id="auth-1",
    )

    assert await service._authenticate_message(connection, database, event) is True
    assert connection.capabilities == {"negative_ack_v1"}
    assert websocket.sent[-1]["payload"]["capabilities"] == ["negative_ack_v1"]


@pytest.mark.asyncio
async def test_auth_retries_invalid_token_then_returns_identity_and_capabilities():
    websocket = FakeWebSocket(
        [
            {"type": "user_auth", "client_msg_id": "bad", "payload": {"username": "alice", "token": "invalid"}},
            {
                "type": "user_auth",
                "client_msg_id": "good",
                "payload": {
                    "username": "alice",
                    "token": "valid",
                    "capabilities": ["negative_ack_v1", "unknown"],
                },
            },
        ]
    )
    connection = WebSocketConnection(websocket, None, None)
    database = SimpleNamespace(
        credential_service=SimpleNamespace(
            check_message_token=lambda _username, token: (token == "valid", "user-1"),
        )
    )
    service = WebSocketService()

    await service.send_system_ready_event(websocket)
    assert await connection.auth(service, database) is True
    assert (connection.user_uuid, connection.user_name) == ("user-1", "alice")
    assert connection.capabilities == {"negative_ack_v1"}
    assert [event["type"] for event in websocket.sent] == ["system_ready", "auth_error", "auth_ok"]
    assert websocket.sent[1]["payload"]["code"] == "INVALID_TOKEN"
    assert websocket.sent[1]["reply_to"] == "bad"
    assert websocket.sent[2]["reply_to"] == "good"
    assert websocket.close_codes == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message, code",
    [
        (ValueError("invalid JSON"), "BAD_JSON"),
        ([], "BAD_MESSAGE"),
        ({"payload": {}}, "BAD_MESSAGE"),
        ({"type": "user_auth", "payload": {"token": "x" * 200}}, "BAD_MESSAGE"),
        ({"type": "user_auth", "payload": {}}, "MISSING_AUTH_FIELDS"),
    ],
)
async def test_auth_rejects_malformed_or_oversized_messages(message, code):
    websocket = FakeWebSocket([message])
    connection = WebSocketConnection(websocket, None, None)
    service = WebSocketService(max_inbound_frame_bytes=128)

    assert await connection.auth(service, object(), max_attempts=1) is False
    assert websocket.sent[0]["payload"]["code"] == code
    assert websocket.sent[-1]["payload"]["code"] == "AUTH_ATTEMPTS_EXCEEDED"
    assert websocket.close_codes == [1008]
    assert connection.user_uuid is None


@pytest.mark.asyncio
async def test_chat_route_does_not_register_stream_after_auth_rejection(monkeypatch):
    from src.web.websocket import endpoint

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
        endpoint,
        "get_admin_shell",
        lambda: SimpleNamespace(runtime_supervisor=SimpleNamespace(runtime=runtime)),
    )

    async def reject_auth(self, _service, _database):
        return False

    monkeypatch.setattr(WebSocketConnection, "auth", reject_auth)

    await endpoint.chat_ws(FakeWebSocket())

    assert registrations == []
