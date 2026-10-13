"""注册接口的真实 HTTP 契约：错误码、原子性与旧客户端零副作用（UA-2）。"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.user.agreement_service import AgreementService
from src.infrastructure.persistence.database.database_service import DatabaseManager
from src.infrastructure.persistence.database.services import credential_service
from src.infrastructure.persistence.database.sql_database import (
    AgreementSignature,
    AgreementVersion,
    InviteCode,
    RegistrationRequest,
    User,
)
from src.web.http import routes
from src.web.http import user_interface as user_interface_module
from src.web.http.rate_limits import enforce_rate_limit
from src.web.http.user_interface import UserInterface

UTC8 = timezone(timedelta(hours=8))
V1 = "terms-2026-10-v1"
V2 = "terms-2026-10-v2"
FIXED_NOW = datetime(2026, 10, 10, 14, 30, 25, tzinfo=UTC8)
INVITE = "INVITE-AAAA"


@pytest.fixture
def register_http(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "ua2-http-secret")
    monkeypatch.setattr(credential_service, "_hash_password", lambda password: f"hash:{password}")
    monkeypatch.setattr(credential_service, "_verify_password", lambda password, stored: stored == f"hash:{password}")
    manager = DatabaseManager({"sql_db_folder": str(tmp_path / "db"), "sql_db_file": "ua2-http.db"})
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
        session.add(InviteCode(code=INVITE, is_used=False, disabled=False))
        session.commit()
    finally:
        session.close()

    ui = UserInterface(manager, SimpleNamespace())
    monkeypatch.setattr(ui, "decrypt_user_password", lambda password: "plain-password")
    # 限流是正交关注点：契约用例各自独立，单独用一条用例验证限流本身（见文件末尾）。
    monkeypatch.setattr(user_interface_module, "enforce_rate_limit", lambda *args, **kwargs: None)
    runtime = SimpleNamespace(user_interface=ui, database_manager=manager)
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes.get_runtime] = lambda: runtime

    def build(current_version=V1):
        runtime.registration_service = __import__(
            "src.application.user.registration_service", fromlist=["RegistrationService"]
        ).RegistrationService(
            agreement_service=AgreementService(current_version, {}),
            credential_service=manager.credential_service,
            clock=lambda: FIXED_NOW,
        )
        return runtime

    with TestClient(app) as client:
        yield SimpleNamespace(client=client, manager=manager, build=build, runtime=runtime)


def counts(manager):
    session = manager.open_sql_session()
    try:
        return {
            "users": session.query(User).count(),
            "signatures": session.query(AgreementSignature).count(),
            "requests": session.query(RegistrationRequest).count(),
            "invite_used": session.query(InviteCode).filter_by(code=INVITE).one().is_used,
        }
    finally:
        session.close()


def test_legacy_client_payload_is_rejected_with_code_and_no_side_effects(register_http):
    register_http.build()

    response = register_http.client.post(
        "/auth/register", json={"username": "newbie", "password": "cipher", "invite_code": INVITE}
    )

    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "AGREEMENT_REQUIRED"
    assert "升级" in body["detail"]
    assert counts(register_http.manager) == {"users": 0, "signatures": 0, "requests": 0, "invite_used": False}


def test_client_supplied_timestamp_is_rejected_by_request_model(register_http):
    register_http.build()

    response = register_http.client.post(
        "/auth/register",
        json={
            "username": "newbie",
            "password": "cipher",
            "invite_code": INVITE,
            "registration_request_id": "req-1",
            "agreement_version": V1,
            "accepted": True,
            "accepted_at": "2026-10-10T14:30:25+08:00",
        },
    )

    assert response.status_code == 422
    assert counts(register_http.manager)["users"] == 0


def test_successful_registration_writes_everything_atomically(register_http):
    register_http.build()

    response = register_http.client.post(
        "/auth/register",
        json={
            "username": "newbie",
            "password": "cipher",
            "invite_code": INVITE,
            "registration_request_id": "req-1",
            "agreement_version": V1,
            "accepted": True,
        },
    )

    assert response.status_code == 200
    assert response.json() == {"message": "注册成功", "user_id": "newbie"}
    assert counts(register_http.manager) == {"users": 1, "signatures": 1, "requests": 1, "invite_used": True}


def test_lost_response_can_be_retried_with_same_request_id(register_http):
    register_http.build()
    payload = {
        "username": "newbie",
        "password": "cipher",
        "invite_code": INVITE,
        "registration_request_id": "req-1",
        "agreement_version": V1,
        "accepted": True,
    }
    first = register_http.client.post("/auth/register", json=payload)

    # 部署已换到 V2，但原请求确实成功过：必须恢复原结果，而不是报换版或"邀请码已用"。
    register_http.build(current_version=V2)
    second = register_http.client.post("/auth/register", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()
    assert counts(register_http.manager) == {"users": 1, "signatures": 1, "requests": 1, "invite_used": True}


def test_same_request_id_with_different_username_conflicts(register_http):
    register_http.build()
    base = {
        "password": "cipher",
        "invite_code": INVITE,
        "registration_request_id": "req-1",
        "agreement_version": V1,
        "accepted": True,
    }
    register_http.client.post("/auth/register", json={**base, "username": "newbie"})

    response = register_http.client.post("/auth/register", json={**base, "username": "other"})

    assert response.status_code == 409
    assert response.json()["code"] == "REGISTRATION_REQUEST_CONFLICT"
    assert counts(register_http.manager)["users"] == 1


def test_new_version_rejects_unfinished_request_without_writes(register_http):
    register_http.build(current_version=V2)

    response = register_http.client.post(
        "/auth/register",
        json={
            "username": "newbie",
            "password": "cipher",
            "invite_code": INVITE,
            "registration_request_id": "req-1",
            "agreement_version": V1,
            "accepted": True,
        },
    )

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "AGREEMENT_CHANGED"
    assert body["agreement_version"] == V2
    assert counts(register_http.manager) == {"users": 0, "signatures": 0, "requests": 0, "invite_used": False}


def test_invalid_invite_keeps_plain_400_detail(register_http):
    register_http.build()

    response = register_http.client.post(
        "/auth/register",
        json={
            "username": "newbie",
            "password": "cipher",
            "invite_code": "NOT-FOUND",
            "registration_request_id": "req-1",
            "agreement_version": V1,
            "accepted": True,
        },
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "注册失败，请检查邀请码或用户名"}


def test_two_request_ids_competing_for_one_invite_code_leave_one_account(register_http):
    register_http.build()
    common = {"password": "cipher", "invite_code": INVITE, "agreement_version": V1, "accepted": True}
    first = register_http.client.post(
        "/auth/register", json={**common, "username": "newbie", "registration_request_id": "req-1"}
    )

    second = register_http.client.post(
        "/auth/register", json={**common, "username": "second", "registration_request_id": "req-2"}
    )

    assert first.status_code == 200
    assert second.status_code == 400
    assert counts(register_http.manager) == {"users": 1, "signatures": 1, "requests": 1, "invite_used": True}


def test_registration_is_rate_limited_per_username(register_http, monkeypatch):
    """已知约束：auth_register 为 5 次 / 60 秒（D13），客户端必须把 429 与真失败区分开。"""
    monkeypatch.setattr(user_interface_module, "enforce_rate_limit", enforce_rate_limit)
    register_http.build()
    payload = {
        "username": "rate-limited-user",
        "password": "cipher",
        "invite_code": INVITE,
        "registration_request_id": "req-rate",
        "agreement_version": V1,
        "accepted": True,
    }

    codes = [register_http.client.post("/auth/register", json=payload).status_code for _ in range(6)]

    assert codes[0] == 200
    assert 429 in codes[1:]
