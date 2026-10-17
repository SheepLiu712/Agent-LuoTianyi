"""协议换版或豁免移除不追溯拦截已建立的真实 WebSocket 会话。"""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.user.agreement_service import AgreementService
from src.infrastructure.media import create_media_resolver
from src.infrastructure.persistence.database.database_service import DatabaseManager
from src.infrastructure.persistence.database.services import credential_service
from src.infrastructure.persistence.database.sql_database import AgreementSignature, AgreementVersion, User
from src.web.http import routes
from src.web.http import user_interface as user_interface_module
from src.web.http.user_interface import UserInterface
from src.web.websocket import endpoint
from src.web.websocket.service import WebSocketService

V1 = "terms-ws-v1"
V2 = "terms-ws-v2"


@pytest.fixture
def agreement_ws(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "agreement-websocket-test-secret")
    monkeypatch.setattr(credential_service, "_hash_password", lambda value: f"hash:{value}")
    monkeypatch.setattr(credential_service, "_is_bcrypt_hash", lambda value: bool(value and value.startswith("hash:")))
    monkeypatch.setattr(credential_service, "_verify_password", lambda value, stored: stored == f"hash:{value}")
    monkeypatch.setattr(user_interface_module, "enforce_rate_limit", lambda *args, **kwargs: None)
    manager = DatabaseManager({"sql_db_folder": str(tmp_path / "db"), "sql_db_file": "agreement-ws.db"})
    session = manager.open_sql_session()
    try:
        for version in (V1, V2):
            session.add(
                AgreementVersion(
                    version=version,
                    title="用户协议",
                    format="agreement.richtext.v1",
                    content_json="[]",
                    content_sha256="0" * 64,
                    created_at="2026-10-10T14:30:25+08:00",
                )
            )
        session.add(User(uuid="ws-user", username="alice", password="hash:password"))
        session.add(
            AgreementSignature(user_uuid="ws-user", agreement_version=V1, accepted_at="2026-10-10T14:30:25+08:00")
        )
        session.commit()
    finally:
        session.close()

    interface = UserInterface(manager, create_media_resolver())
    monkeypatch.setattr(interface, "decrypt_user_password", lambda value: value)
    connected = []
    disconnected = []

    async def connect(connection, character_id):
        connected.append((connection.user_uuid, character_id))

    async def disconnect(connection):
        disconnected.append(connection.user_uuid)

    def record_login(*_args, **_kwargs):
        return True

    runtime = SimpleNamespace(
        database_manager=manager,
        agreement_service=AgreementService(V1, {}),
        websocket_service=WebSocketService(),
        stage_manager=SimpleNamespace(connect=connect, disconnect=disconnect, record_login=record_login),
        agent_runtime=SimpleNamespace(default_character_id="luotianyi"),
        client_llm_executor=SimpleNamespace(clear_user=lambda *_args: None),
        user_interface=interface,
    )
    manager.conversation_service.prefill_buffer = lambda _user_uuid: None
    app = FastAPI()
    app.include_router(routes.router)
    app.include_router(endpoint.router)
    app.dependency_overrides[routes.get_runtime] = lambda: runtime
    monkeypatch.setattr(
        endpoint,
        "get_admin_shell",
        lambda: SimpleNamespace(runtime_supervisor=SimpleNamespace(runtime=runtime)),
    )
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, runtime=runtime, connected=connected, disconnected=disconnected)


def _login(client):
    return client.post("/auth/login", json={"username": "alice", "password": "password"})


@pytest.mark.parametrize("policy", ["version_change", "remove_exemption"])
def test_established_websocket_remains_authenticated_after_policy_changes_but_next_login_is_gated(agreement_ws, policy):
    if policy == "remove_exemption":
        session = agreement_ws.runtime.database_manager.open_sql_session()
        try:
            session.query(AgreementSignature).filter_by(user_uuid="ws-user", agreement_version=V1).delete()
            session.commit()
        finally:
            session.close()
        agreement_ws.runtime.agreement_service = AgreementService(V1, {}, {"ws-user"})

    login = _login(agreement_ws.client)
    assert login.status_code == 200

    with agreement_ws.client.websocket_connect("/chat_ws") as websocket:
        assert websocket.receive_json()["type"] == "system_ready"
        websocket.send_json(
            {
                "type": "user_auth",
                "client_msg_id": "auth-before-policy-change",
                "payload": {"username": "alice", "token": login.json()["message_token"]},
            }
        )
        assert websocket.receive_json()["type"] == "auth_ok"
        assert agreement_ws.connected == [("ws-user", "luotianyi")]

        agreement_ws.runtime.agreement_service = (
            AgreementService(V2, {}) if policy == "version_change" else AgreementService(V1, {})
        )
        websocket.send_json(
            {
                "type": "hb_ping",
                "client_msg_id": "still-connected",
                "payload": {"ping_id": 1},
            }
        )
        assert websocket.receive_json()["type"] == "hb_pong"

    blocked = _login(agreement_ws.client)
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "AGREEMENT_REQUIRED"
