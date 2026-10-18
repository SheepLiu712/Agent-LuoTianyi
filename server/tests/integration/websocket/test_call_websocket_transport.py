import asyncio
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient


from src.server_runtime import CallCapabilityStatus
from src.web.websocket import call_endpoint

CALL_ID = "606ec5e6-a330-4e6c-b07a-8432a5716c8f"


class Sink:
    def __init__(self) -> None:
        self.frames: list = []

    async def accept(self, frame, receipt) -> bool:
        del receipt
        self.frames.append(frame)
        return True


class CredentialService:
    @staticmethod
    def check_message_token(username, token):
        return (username == "alice" and token == "valid-token", "user-1")


def runtime(*, available: bool):
    from src.web.websocket import WebSocketService

    sink = Sink()
    return (
        SimpleNamespace(
            websocket_service=WebSocketService(),
            database_manager=SimpleNamespace(credential_service=CredentialService()),
            call_capability=CallCapabilityStatus(*(available for _ in range(8)), ("luotianyi",) if available else ()),
            supports_call_character=lambda character_id: available and character_id == "luotianyi",
        ),
        None,
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
