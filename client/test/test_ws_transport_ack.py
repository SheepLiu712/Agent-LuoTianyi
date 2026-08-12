import asyncio
import json

from src.network.event_types import WSEventType
from src.network.ws_transport import WsTransport, normalize_server_ack


def test_legacy_ack_is_successful():
    assert normalize_server_ack({"received_event_type": "user_text"}) == {
        "ok": True,
        "error": None,
    }


def test_overload_ack_is_retryable():
    assert normalize_server_ack(
        {
            "ok": False,
            "code": "OVERLOADED",
            "message": "ingress queue is full",
            "retryable": True,
        }
    ) == {
        "ok": False,
        "error": "[OVERLOADED] ingress queue is full",
        "code": "OVERLOADED",
        "retryable": True,
        "drop": False,
    }


def test_permanent_rejection_is_terminal():
    ack = normalize_server_ack({"ok": False, "code": "BAD_MESSAGE"})

    assert ack["ok"] is False
    assert ack["retryable"] is False
    assert ack["drop"] is True


def _ready_transport():
    transport = WsTransport("http://localhost:60030", lambda: "alice", lambda: "token")
    transport.start = lambda: None
    transport._ready_event.set()
    return transport


def test_send_race_keeps_message_retryable():
    transport = _ready_transport()
    transport._send_event = lambda _event: False

    result = transport._submit_user_event(
        WSEventType.USER_TEXT,
        {"message": "hello"},
        ack_timeout=0.1,
        client_msg_id="msg-1",
    )

    assert result["ok"] is False
    assert result["drop"] is False


def test_ack_timeout_keeps_same_message_retryable():
    transport = _ready_transport()
    transport._send_event = lambda _event: True

    result = transport._submit_user_event(
        WSEventType.USER_TEXT,
        {"message": "hello"},
        ack_timeout=0.01,
        client_msg_id="msg-1",
    )

    assert result["request_id"] == "msg-1"
    assert result["drop"] is False


def test_temporary_not_ready_keeps_same_message_retryable():
    transport = WsTransport("http://localhost:60030", lambda: "alice", lambda: "token")
    transport.start = lambda: None
    transport.READY_TIMEOUT_SECONDS = 0.01

    result = transport._submit_user_event(
        WSEventType.USER_TEXT,
        {"message": "hello"},
        ack_timeout=0.01,
        client_msg_id="msg-not-ready",
    )

    assert result["request_id"] == "msg-not-ready"
    assert result["retryable"] is True
    assert result["drop"] is False


def test_explicit_auth_rejection_is_terminal():
    transport = WsTransport("http://localhost:60030", lambda: "alice", lambda: "bad-token")
    transport.start = lambda: None
    transport._mark_auth_rejected()

    result = transport._submit_user_event(
        WSEventType.USER_TEXT,
        {"message": "hello"},
        ack_timeout=0.01,
        client_msg_id="msg-auth-rejected",
    )

    assert result["request_id"] == "msg-auth-rejected"
    assert result["code"] == "AUTH_REJECTED"
    assert result["retryable"] is False
    assert result["drop"] is True


def test_auth_payload_advertises_negative_ack_support():
    class FakeWebSocket:
        def __init__(self):
            self.sent = []
            self.responses = [
                json.dumps({"type": "system_ready", "payload": {}}),
                json.dumps({"type": "auth_ok", "payload": {}}),
            ]

        async def recv(self):
            return self.responses.pop(0)

        async def send(self, raw):
            self.sent.append(json.loads(raw))

    transport = WsTransport("http://localhost:60030", lambda: "alice", lambda: "token")
    websocket = FakeWebSocket()

    asyncio.run(transport._authenticate(websocket))

    assert websocket.sent[0]["payload"] == {
        "username": "alice",
        "token": "token",
        "capabilities": ["negative_ack_v1"],
    }


def test_unmatched_websocket_error_is_routed_as_system_message():
    transport = WsTransport("http://localhost:60030", lambda: "alice", lambda: "token")
    agent_messages = []
    system_messages = []
    transport.set_agent_message_listener(
        agent_messages.append,
        lambda _state: None,
        system_messages.append,
    )

    class FakeWebSocket:
        async def recv(self):
            transport._stop_event.set()
            return json.dumps({
                "type": "error",
                "payload": {"code": "WS_FAILED", "message": "WebSocket 错误"},
            })

    asyncio.run(transport._recv_loop(FakeWebSocket()))

    assert system_messages == ["[WS_FAILED] WebSocket 错误"]
    assert agent_messages == []
