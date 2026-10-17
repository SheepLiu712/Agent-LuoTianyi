"""协议签署与密码/自动登录门禁的真实 HTTP 契约。"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.user import agreement_service as agreement_service_module
from src.application.user.agreement_service import AgreementService, first_signed_at
from src.infrastructure.media import create_media_resolver
from src.infrastructure.persistence.database.database_service import DatabaseManager
from src.infrastructure.persistence.database.services import credential_service
from src.infrastructure.persistence.database.sql_database import AgreementSignature, AgreementVersion, InviteCode, User
from src.web.http import routes
from src.web.http import user_interface as user_interface_module
from src.web.http.user_interface import UserInterface

UTC8 = timezone(timedelta(hours=8))
V1 = "terms-v1"
V2 = "terms-v2"


@pytest.fixture
def agreement_http(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "agreement-gate-test-secret")
    monkeypatch.setattr(credential_service, "_hash_password", lambda value: f"hash:{value}")
    monkeypatch.setattr(credential_service, "_is_bcrypt_hash", lambda value: bool(value and value.startswith("hash:")))
    monkeypatch.setattr(credential_service, "_verify_password", lambda value, stored: stored == f"hash:{value}")
    manager = DatabaseManager({"sql_db_folder": str(tmp_path / "db"), "sql_db_file": "agreement-gate.db"})
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
        session.add(User(uuid="user-1", username="alice", password="hash:password"))
        session.add(User(uuid="user-2", username="exempt", password="hash:password"))
        session.commit()
    finally:
        session.close()

    logins = []
    prefilled = []
    interface = UserInterface(manager, create_media_resolver())
    monkeypatch.setattr(interface, "decrypt_user_password", lambda value: value)
    monkeypatch.setattr(user_interface_module, "enforce_rate_limit", lambda *args, **kwargs: None)
    runtime = SimpleNamespace(
        database_manager=manager,
        agreement_service=AgreementService(V1, {}, {"user-2"}),
        agent_runtime=SimpleNamespace(default_character_id="luotianyi"),
        stage_manager=SimpleNamespace(record_login=lambda *args, **kwargs: logins.append((args, kwargs))),
    )
    manager.conversation_service.prefill_buffer = lambda user_uuid: prefilled.append(user_uuid)
    runtime.user_interface = interface
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes.get_runtime] = lambda: runtime
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, manager=manager, runtime=runtime, logins=logins, prefilled=prefilled)


def login(client, username="alice", password="password"):
    return client.post("/auth/login", json={"username": username, "password": password})


def accept_password(client, version=V1, accepted=True):
    return client.post(
        "/auth/agreement/accept",
        json={
            "agreement_version": version,
            "accepted": accepted,
            "credential": {"kind": "password", "username": "alice", "password": "password"},
        },
    )


def test_unsigned_password_login_is_gated_without_login_side_effects(agreement_http):
    response = login(agreement_http.client)

    assert response.status_code == 403
    assert response.json() == {
        "detail": "请升级到支持用户协议签署的版本，阅读并同意用户协议后再登录。",
        "code": "AGREEMENT_REQUIRED",
        "agreement_version": V1,
    }
    session = agreement_http.manager.open_sql_session()
    try:
        user = session.query(User).filter_by(username="alice").one()
        assert user.auth_token is None
        assert user.last_login is None
        assert session.query(AgreementSignature).count() == 0
    finally:
        session.close()
    assert agreement_http.logins == []
    assert agreement_http.prefilled == []


def test_bad_credentials_do_not_disclose_agreement_state(agreement_http):
    response = login(agreement_http.client, password="wrong")

    assert response.status_code == 401
    assert response.json() == {"detail": "用户名或密码错误"}


def test_password_acceptance_is_idempotent_and_requires_independent_login(agreement_http):
    first = accept_password(agreement_http.client)
    second = accept_password(agreement_http.client)

    assert first.status_code == 200
    assert second.json() == first.json()
    assert set(first.json()) == {"agreement_version", "accepted_at"}
    parsed = datetime.fromisoformat(first.json()["accepted_at"])
    assert parsed.utcoffset() == timedelta(hours=8)
    assert parsed.microsecond == 0
    session = agreement_http.manager.open_sql_session()
    try:
        user = session.query(User).filter_by(username="alice").one()
        assert user.auth_token is None
        assert user.last_login is None
        assert session.query(AgreementSignature).count() == 1
    finally:
        session.close()

    assert login(agreement_http.client).status_code == 200


def test_acceptance_rejects_changed_version_and_non_explicit_consent(agreement_http):
    changed = accept_password(agreement_http.client, version=V2)
    not_accepted = accept_password(agreement_http.client, accepted=False)

    assert changed.status_code == 409
    assert changed.json()["code"] == "AGREEMENT_CHANGED"
    assert changed.json()["agreement_version"] == V1
    assert not_accepted.status_code == 422
    session = agreement_http.manager.open_sql_session()
    try:
        assert session.query(AgreementSignature).count() == 0
    finally:
        session.close()


def test_auto_login_gate_preserves_valid_token_then_accepts_independently(agreement_http):
    token = agreement_http.manager.credential_service.update_auth_token("alice")
    blocked = agreement_http.client.post("/auth/auto_login", json={"username": "alice", "token": token})

    assert blocked.status_code == 403
    assert agreement_http.manager.credential_service.check_auth_token("alice", token) is True
    accepted = agreement_http.client.post(
        "/auth/agreement/accept",
        json={
            "agreement_version": V1,
            "accepted": True,
            "credential": {"kind": "auto_login", "username": "alice", "token": token},
        },
    )
    logged_in = agreement_http.client.post("/auth/auto_login", json={"username": "alice", "token": token})

    assert accepted.status_code == 200
    assert logged_in.status_code == 200
    assert logged_in.json()["login_token"] != token


def test_exempt_user_still_requires_valid_credentials_but_needs_no_signature(agreement_http):
    response = login(agreement_http.client, username="exempt")

    assert response.status_code == 200
    session = agreement_http.manager.open_sql_session()
    try:
        assert session.query(AgreementSignature).filter_by(user_uuid="user-2").count() == 0
    finally:
        session.close()


def test_version_change_requires_a_new_signature_on_the_next_login(agreement_http):
    assert accept_password(agreement_http.client, V1).status_code == 200
    agreement_http.runtime.agreement_service = AgreementService(V2, {}, set())

    response = login(agreement_http.client)

    assert response.status_code == 403
    assert response.json()["agreement_version"] == V2


def test_signatures_are_isolated_by_version_and_keep_their_first_time(agreement_http):
    first = accept_password(agreement_http.client, V1)
    agreement_http.runtime.agreement_service = AgreementService(V2, {}, set())
    second = accept_password(agreement_http.client, V2)

    session = agreement_http.manager.open_sql_session()
    try:
        assert first_signed_at(session, "user-1", V1) == first.json()["accepted_at"]
        assert first_signed_at(session, "user-1", V2) == second.json()["accepted_at"]
    finally:
        session.close()


def test_reset_keeps_signature_but_changes_the_credentials_used_for_acceptance(agreement_http):
    assert accept_password(agreement_http.client).status_code == 200
    session = agreement_http.manager.open_sql_session()
    try:
        session.add(InviteCode(code="RESET-INVITE", is_used=True, user_id="user-1"))
        session.commit()
    finally:
        session.close()

    assert agreement_http.manager.credential_service.reset_account("RESET-INVITE", "alice-renamed", "new-password")[0]
    session = agreement_http.manager.open_sql_session()
    try:
        assert first_signed_at(session, "user-1", V1) is not None
    finally:
        session.close()
    assert login(agreement_http.client, username="alice-renamed", password="new-password").status_code == 200


def test_removing_exemption_restores_login_gate_without_revoking_existing_session(agreement_http):
    first = login(agreement_http.client, username="exempt")
    agreement_http.runtime.agreement_service = AgreementService(V1, {}, set())
    blocked = login(agreement_http.client, username="exempt")

    assert first.status_code == 200
    assert blocked.status_code == 403
    assert agreement_http.manager.credential_service.check_message_token("exempt", first.json()["message_token"])[0]


def test_signature_write_failure_rolls_back_without_issuing_a_login(agreement_http, monkeypatch):
    def fail_signature(*args, **kwargs):
        raise RuntimeError("write failed")

    monkeypatch.setattr(agreement_service_module, "record_signature", fail_signature)
    with pytest.raises(RuntimeError):
        accept_password(agreement_http.client)

    session = agreement_http.manager.open_sql_session()
    try:
        user = session.query(User).filter_by(username="alice").one()
        assert user.auth_token is None
        assert user.last_login is None
        assert session.query(AgreementSignature).count() == 0
    finally:
        session.close()
