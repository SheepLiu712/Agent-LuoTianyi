"""共享 HTTP 协议与持久库的跨客户端语义集成测试，不替代真实客户端 E2E。"""

from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.user.agreement_service import AgreementService
from src.application.user.registration_service import RegistrationService
from src.infrastructure.media import create_media_resolver
from src.infrastructure.persistence.database.database_service import DatabaseManager
from src.infrastructure.persistence.database.sql_database import AgreementSignature, AgreementVersion, InviteCode, User
from src.web.http import rate_limits, routes
from src.web.http.user_interface import UserInterface

V1 = "terms-cross-v1"
V2 = "terms-cross-v2"


class ServerClient:
    def __init__(self, client: TestClient) -> None:
        self._client = client

    def __enter__(self) -> TestClient:
        return self._client

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self._client.close()


@pytest.fixture
def cross_client(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "cross-client-agreement-secret")
    rate_limits._reset_rate_limit_state()
    database_config = {"sql_db_folder": str(tmp_path / "db"), "sql_db_file": "cross-client.db"}
    manager = DatabaseManager(database_config)
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
        for code in ("DESKTOP-INVITE", "APP-INVITE", "RECOVERY-INVITE"):
            session.add(InviteCode(code=code, is_used=False, disabled=False))
        session.commit()
    finally:
        session.close()

    def new_server(current_version=V1):
        interface = UserInterface(manager, create_media_resolver())
        interface.generate_rsa_keys()
        runtime = SimpleNamespace(
            database_manager=manager,
            agreement_service=AgreementService(current_version, {}),
            registration_service=RegistrationService(
                agreement_service=AgreementService(current_version, {}),
                credential_service=manager.credential_service,
            ),
            agent_runtime=SimpleNamespace(default_character_id="luotianyi"),
            stage_manager=SimpleNamespace(record_login=lambda *args, **kwargs: True),
            user_interface=interface,
        )
        manager.conversation_service.prefill_buffer = lambda _user_uuid: None
        app = FastAPI()
        app.include_router(routes.router)
        app.dependency_overrides[routes.get_runtime] = lambda: runtime
        return ServerClient(TestClient(app)), runtime

    yield SimpleNamespace(manager=manager, new_server=new_server)
    rate_limits._reset_rate_limit_state()


def _encrypt_password(client: TestClient, password: str) -> str:
    pem = client.get("/auth/public_key").json()["public_key"]
    public_key = serialization.load_pem_public_key(pem.encode("utf-8"))
    return (
        __import__("base64")
        .b64encode(
            public_key.encrypt(
                password.encode("utf-8"),
                padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
            )
        )
        .decode("ascii")
    )


def _register(client, *, username: str, password: str, invite_code: str, request_id: str, version=V1):
    return client.post(
        "/auth/register",
        json={
            "username": username,
            "password": _encrypt_password(client, password),
            "invite_code": invite_code,
            "registration_request_id": request_id,
            "agreement_version": version,
            "accepted": True,
        },
    )


def _login(client, username: str, password: str):
    return client.post("/auth/login", json={"username": username, "password": _encrypt_password(client, password)})


def _accept_password(client, *, username: str, password: str, version=V1):
    return client.post(
        "/auth/agreement/accept",
        json={
            "agreement_version": version,
            "accepted": True,
            "credential": {"kind": "password", "username": username, "password": _encrypt_password(client, password)},
        },
    )


def test_registration_persisted_by_one_http_client_allows_another_client_login_without_resigning(cross_client):
    desktop, _ = cross_client.new_server()
    with desktop as desktop_server:
        registered = _register(
            desktop_server,
            username="desktop-user",
            password="desktop-password",
            invite_code="DESKTOP-INVITE",
            request_id="desktop-registration",
        )
    app, _ = cross_client.new_server()
    with app as app_server:
        logged_in = _login(app_server, "desktop-user", "desktop-password")

    assert registered.status_code == 200
    assert logged_in.status_code == 200


def test_registration_persisted_by_a_fresh_http_client_allows_another_client_login_without_resigning(cross_client):
    app, _ = cross_client.new_server()
    with app as app_server:
        registered = _register(
            app_server,
            username="app-user",
            password="app-password",
            invite_code="APP-INVITE",
            request_id="app-registration",
        )
    desktop, _ = cross_client.new_server()
    with desktop as desktop_server:
        logged_in = _login(desktop_server, "app-user", "app-password")

    assert registered.status_code == 200
    assert logged_in.status_code == 200


def test_one_client_signature_allows_another_to_login_and_v2_requires_resigning(cross_client):
    first, _ = cross_client.new_server()
    with first as first_client:
        _register(
            first_client,
            username="legacy-user",
            password="legacy-password",
            invite_code="RECOVERY-INVITE",
            request_id="legacy-registration",
        )
        session = cross_client.manager.open_sql_session()
        try:
            user = session.query(User).filter_by(username="legacy-user").one()
            session.query(AgreementSignature).filter_by(user_uuid=user.uuid, agreement_version=V1).delete()
            session.commit()
        finally:
            session.close()
        accepted = _accept_password(first_client, username="legacy-user", password="legacy-password")
    second, _ = cross_client.new_server()
    with second as second_client:
        v1_login = _login(second_client, "legacy-user", "legacy-password")
    v2, _ = cross_client.new_server(V2)
    with v2 as v2_client:
        v2_blocked = _login(v2_client, "legacy-user", "legacy-password")
        v2_accepted = _accept_password(v2_client, username="legacy-user", password="legacy-password", version=V2)
        v2_login = _login(v2_client, "legacy-user", "legacy-password")

    assert accepted.status_code == 200
    assert v1_login.status_code == 200
    assert v2_blocked.status_code == 403
    assert v2_accepted.status_code == 200
    assert v2_login.status_code == 200
    session = cross_client.manager.open_sql_session()
    try:
        assert session.query(AgreementSignature).filter_by(agreement_version=V1).count() == 1
        assert session.query(AgreementSignature).filter_by(agreement_version=V2).count() == 1
    finally:
        session.close()


def test_lost_signature_response_recovers_first_time_after_new_server_instance(cross_client):
    first, _ = cross_client.new_server()
    with first as first_server:
        _register(
            first_server,
            username="signature-retry",
            password="retry-password",
            invite_code="RECOVERY-INVITE",
            request_id="signature-retry-registration",
        )
        session = cross_client.manager.open_sql_session()
        try:
            user = session.query(User).filter_by(username="signature-retry").one()
            session.query(AgreementSignature).filter_by(user_uuid=user.uuid, agreement_version=V1).delete()
            session.commit()
        finally:
            session.close()
        committed = _accept_password(first_server, username="signature-retry", password="retry-password")
    retry, _ = cross_client.new_server()
    with retry as retry_server:
        retried = _accept_password(retry_server, username="signature-retry", password="retry-password")

    assert committed.status_code == 200
    assert retried.status_code == 200
    assert retried.json() == committed.json()
    session = cross_client.manager.open_sql_session()
    try:
        row = session.query(AgreementSignature).filter_by(agreement_version=V1).one()
        assert retried.json()["accepted_at"] == row.accepted_at
    finally:
        session.close()


def test_lost_registration_response_recovers_after_new_server_instance(cross_client):
    first, _ = cross_client.new_server()
    with first as first_server:
        committed = _register(
            first_server,
            username="registration-retry",
            password="retry-password",
            invite_code="RECOVERY-INVITE",
            request_id="registration-retry-id",
        )
    retry, _ = cross_client.new_server(V2)
    with retry as retry_server:
        retried = _register(
            retry_server,
            username="registration-retry",
            password="retry-password",
            invite_code="RECOVERY-INVITE",
            request_id="registration-retry-id",
        )

    assert committed.status_code == 200
    assert retried.status_code == 200
    assert retried.json() == {"message": "注册成功", "user_id": "registration-retry"}


def test_auto_login_token_is_unchanged_until_independent_login_after_signature(cross_client):
    instance, _ = cross_client.new_server()
    with instance as server:
        _register(
            server,
            username="token-user",
            password="token-password",
            invite_code="RECOVERY-INVITE",
            request_id="token-registration",
        )
        session = cross_client.manager.open_sql_session()
        try:
            user = session.query(User).filter_by(username="token-user").one()
            session.query(AgreementSignature).filter_by(user_uuid=user.uuid, agreement_version=V1).delete()
            session.commit()
        finally:
            session.close()
        token = cross_client.manager.credential_service.update_auth_token("token-user")
        blocked = server.post("/auth/auto_login", json={"username": "token-user", "token": token})
        accepted = server.post(
            "/auth/agreement/accept",
            json={
                "agreement_version": V1,
                "accepted": True,
                "credential": {"kind": "auto_login", "username": "token-user", "token": token},
            },
        )
        preserved_after_accept = cross_client.manager.credential_service.check_auth_token("token-user", token)
        logged_in = server.post("/auth/auto_login", json={"username": "token-user", "token": token})

    assert blocked.status_code == 403
    assert accepted.status_code == 200
    assert preserved_after_accept is True
    assert logged_in.status_code == 200
    assert logged_in.json()["login_token"] != token
