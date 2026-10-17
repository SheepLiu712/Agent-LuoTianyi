"""协议签署的凭据原子性、限流及输入门禁。"""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.user.agreement_service import AgreementService
from src.infrastructure.media import create_media_resolver
from src.infrastructure.persistence.database.database_service import DatabaseManager
from src.infrastructure.persistence.database.services import credential_service
from src.infrastructure.persistence.database.sql_database import AgreementSignature, AgreementVersion, InviteCode, User
from src.web.http import rate_limits, routes
from src.web.http.user_interface import UserInterface

V1 = "terms-security-v1"


@pytest.fixture
def agreement_security_http(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "agreement-security-test-secret")
    monkeypatch.setattr(credential_service, "_hash_password", lambda value: f"hash:{value}")
    monkeypatch.setattr(credential_service, "_is_bcrypt_hash", lambda value: bool(value and value.startswith("hash:")))
    monkeypatch.setattr(credential_service, "_verify_password", lambda value, stored: stored == f"hash:{value}")
    rate_limits._reset_rate_limit_state()
    manager = DatabaseManager({"sql_db_folder": str(tmp_path / "db"), "sql_db_file": "agreement-security.db"})
    session = manager.open_sql_session()
    try:
        session.add(
            AgreementVersion(
                version=V1,
                title="用户协议",
                format="agreement.richtext.v1",
                content_json="[]",
                content_sha256="0" * 64,
                created_at="2026-10-10T14:30:25+08:00",
            )
        )
        session.add(User(uuid="security-user", username="alice", password="hash:password"))
        session.add(InviteCode(code="RESET-INVITE", is_used=True, user_id="security-user"))
        session.commit()
    finally:
        session.close()

    interface = UserInterface(manager, create_media_resolver())
    monkeypatch.setattr(interface, "decrypt_user_password", lambda value: value)
    runtime = SimpleNamespace(
        database_manager=manager,
        agreement_service=AgreementService(V1, {}),
        agent_runtime=SimpleNamespace(default_character_id="luotianyi"),
        stage_manager=SimpleNamespace(record_login=lambda *args, **kwargs: None),
        user_interface=interface,
    )
    manager.conversation_service.prefill_buffer = lambda _user_uuid: None
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes.get_runtime] = lambda: runtime
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, manager=manager)
    rate_limits._reset_rate_limit_state()


def _accept_password(client, *, password="password"):
    return client.post(
        "/auth/agreement/accept",
        json={
            "agreement_version": V1,
            "accepted": True,
            "credential": {"kind": "password", "username": "alice", "password": password},
        },
    )


def _accept_auto_login(client, token):
    return client.post(
        "/auth/agreement/accept",
        json={
            "agreement_version": V1,
            "accepted": True,
            "credential": {"kind": "auto_login", "username": "alice", "token": token},
        },
    )


@pytest.mark.parametrize("credential_kind", ["password", "auto_login"])
def test_reset_between_identity_check_and_signature_rejects_stale_credentials(
    agreement_security_http, monkeypatch, credential_kind
):
    credentials = agreement_security_http.manager.credential_service
    original_lock = credentials.lock_current_agreement_identity
    token = credentials.update_auth_token("alice") if credential_kind == "auto_login" else None
    reset_done = False

    def reset_before_atomic_credential_check(*args, **kwargs):
        nonlocal reset_done
        if not reset_done:
            reset_done = True
            assert credentials.reset_account("RESET-INVITE", "alice-reset", "new-password")[0]
        return original_lock(*args, **kwargs)

    monkeypatch.setattr(credentials, "lock_current_agreement_identity", reset_before_atomic_credential_check)
    response = (
        _accept_password(agreement_security_http.client)
        if credential_kind == "password"
        else _accept_auto_login(agreement_security_http.client, token)
    )

    assert reset_done is True
    assert response.status_code == 401
    assert response.json() == {"detail": "身份验证失败"}
    session = agreement_security_http.manager.open_sql_session()
    try:
        assert session.query(AgreementSignature).count() == 0
    finally:
        session.close()


def test_valid_signature_does_not_login_and_remains_idempotent(agreement_security_http):
    first = _accept_password(agreement_security_http.client)
    second = _accept_password(agreement_security_http.client)

    assert first.status_code == 200
    assert second.json() == first.json()
    session = agreement_security_http.manager.open_sql_session()
    try:
        user = session.query(User).filter_by(username="alice").one()
        assert user.auth_token is None
        assert user.last_login is None
        assert session.query(AgreementSignature).count() == 1
    finally:
        session.close()


@pytest.mark.parametrize("credential_kind", ["password", "auto_login"])
def test_accept_reuses_its_authentication_rate_limit(agreement_security_http, credential_kind):
    for _ in range(10):
        response = (
            _accept_password(agreement_security_http.client, password="wrong")
            if credential_kind == "password"
            else _accept_auto_login(agreement_security_http.client, "not-a-valid-token")
        )
        assert response.status_code == 401

    limited = (
        _accept_password(agreement_security_http.client, password="wrong")
        if credential_kind == "password"
        else _accept_auto_login(agreement_security_http.client, "not-a-valid-token")
    )

    assert limited.status_code == 429
    assert limited.json() == {"detail": "请求过于频繁，请稍后再试"}


def test_invalid_auto_login_token_does_not_disclose_agreement_state(agreement_security_http):
    response = _accept_auto_login(agreement_security_http.client, "not-a-valid-token")

    assert response.status_code == 401
    assert response.json() == {"detail": "身份验证失败"}
    session = agreement_security_http.manager.open_sql_session()
    try:
        assert session.query(AgreementSignature).count() == 0
    finally:
        session.close()


@pytest.mark.parametrize(
    "payload",
    [
        {
            "agreement_version": V1,
            "accepted": "true",
            "credential": {"kind": "password", "username": "alice", "password": "password"},
        },
        {
            "agreement_version": V1,
            "accepted": True,
            "credential": {"kind": "password", "username": "alice", "password": "password", "token": "extra"},
        },
        {
            "agreement_version": V1,
            "accepted": True,
            "credential": {"kind": "auto_login", "username": "alice", "token": "x", "password": "extra"},
        },
    ],
)
def test_accept_rejects_non_strict_or_mutually_exclusive_credential_fields(agreement_security_http, payload):
    response = agreement_security_http.client.post("/auth/agreement/accept", json=payload)

    assert response.status_code == 422
    session = agreement_security_http.manager.open_sql_session()
    try:
        assert session.query(AgreementSignature).count() == 0
    finally:
        session.close()
