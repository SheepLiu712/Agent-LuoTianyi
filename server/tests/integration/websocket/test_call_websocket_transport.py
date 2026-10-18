import asyncio
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.adapter.websocket.call_v1._transport import (
    _CallAcceptanceReceipt,
    _CallTransportHub,
    _CallTransportSession,
    _InboundCallFrame,
)
from src.server_runtime import CallCapabilityStatus
from src.web.websocket import call_endpoint

CALL_ID = "606ec5e6-a330-4e6c-b07a-8432a5716c8f"


class Sink:
    def __init__(self) -> None:
        self.frames: list[_InboundCallFrame] = []

    async def accept(self, frame: _InboundCallFrame, receipt: _CallAcceptanceReceipt) -> bool:
        del receipt
        self.frames.append(frame)
        return True


class CredentialService:
    @staticmethod
    def check_message_token(username, token):
        return (username == "alice" and token == "valid-token", "user-1")


def runtime(*, available: bool):
    from src.web.websocket import WebSocketService

    hub = _CallTransportHub()
    sink = Sink()
    session = _CallTransportSession(call_id=CALL_ID, user_id="user-1", character_id="luotianyi", sink=sink)
    hub.register(session)
    return (
        SimpleNamespace(
            websocket_service=WebSocketService(),
            database_manager=SimpleNamespace(credential_service=CredentialService()),
            call_capability=CallCapabilityStatus(*(available for _ in range(8)), ("luotianyi",) if available else ()),
            supports_call_character=lambda character_id: available and character_id == "luotianyi",
            call_transport_hub=hub,
        ),
        session,
        sink,
    )


def app_for(monkeypatch, configured_runtime):
    app = FastAPI()
    app.include_router(call_endpoint.router)
    monkeypatch.setattr(
        call_endpoint,
        "get_admin_shell",
        lambda: SimpleNamespace(runtime_supervisor=SimpleNamespace(runtime=configured_runtime)),
    )
    return app


def auth(websocket):
    assert websocket.receive_json()["type"] == "system_ready"
    websocket.send_json(
        {
            "type": "user_auth",
            "client_msg_id": "auth-1",
            "payload": {"username": "alice", "token": "valid-token"},
        }
    )
    assert websocket.receive_json()["type"] == "auth_ok"


def test_call_endpoint_is_unavailable_by_default(monkeypatch):
    configured_runtime, _, _ = runtime(available=False)
    with TestClient(app_for(monkeypatch, configured_runtime)) as client:
        try:
            with client.websocket_connect("/call_ws") as websocket:
                websocket.receive_text()
        except Exception as error:
            assert getattr(error, "code", None) == 1013


def test_call_endpoint_rejects_call_start_without_production_adapter(monkeypatch):
    configured_runtime, _, sink = runtime(available=True)
    with TestClient(app_for(monkeypatch, configured_runtime)) as client:
        try:
            with client.websocket_connect("/call_ws") as websocket:
                auth(websocket)
                websocket.send_text(
                    json.dumps(
                        {
                            "protocol": "call.v1",
                            "type": "call.start",
                            "seq": 1,
                            "client_request_id": "request-1",
                            "character_id": "luotianyi",
                            "audio": {
                                "encoding": "pcm_s16le",
                                "sample_rate": 16000,
                                "channels": 1,
                            },
                        },
                        separators=(",", ":"),
                    )
                )
                websocket.receive_text()
        except Exception as error:
            assert getattr(error, "code", None) == 1013
    assert sink.frames == []


def test_hub_rejects_second_active_connection_and_allows_resume_after_detach():
    _, session, _ = runtime(available=True)
    hub = _CallTransportHub()
    hub.register(session)
    raw = json.dumps(
        {
            "protocol": "call.v1",
            "type": "call.resume",
            "call_id": CALL_ID,
            "character_id": "luotianyi",
            "last_contiguous_server_seq": 0,
        },
        separators=(",", ":"),
    )

    async def scenario():
        first = await hub.attach_resume(raw, user_id="user-1", connection_id=object())
        try:
            await hub.attach_resume(raw, user_id="user-1", connection_id=object())
            raise AssertionError("second active connection was accepted")
        except Exception as error:
            assert getattr(error, "code", None) == "CALL_CONNECTION_ACTIVE"
        assert await hub.detach(first) is True
        second = await hub.attach_resume(raw, user_id="user-1", connection_id=object())
        assert second.generation == first.generation + 1
        before = session.server_ack_cursor
        try:
            hub.acknowledge_bound(first, before)
            raise AssertionError("stale binding changed ACK state")
        except Exception as error:
            assert getattr(error, "code", None) == "STALE_CALL_CONNECTION"
        assert session.server_ack_cursor == before
        assert await hub.detach(first) is False
        assert hub.is_current(second)

    asyncio.run(scenario())


def test_hub_unregister_requires_expected_session_and_closes_registered_state():
    _, session, _ = runtime(available=True)
    hub = _CallTransportHub()
    hub.register(session)
    other = _CallTransportSession(call_id=CALL_ID, user_id="user-1", character_id="luotianyi", sink=Sink())

    async def scenario():
        assert await hub.unregister(CALL_ID, expected_session=other) is False
        assert await hub.unregister(CALL_ID, expected_session=session) is True
        try:
            session.replay_after(0)
            raise AssertionError("unregistered session remained open")
        except Exception as error:
            assert getattr(error, "code", None) == "TRANSPORT_CLOSED"

    asyncio.run(scenario())
