"""注册入口的错误码映射：旧客户端 403、换版 409、冲突 409，且都不产生副作用。"""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from src.application.user.agreement_service import AgreementService
from src.application.user.registration_service import RegistrationService
from src.infrastructure.persistence.database.database_service import DatabaseManager
from src.infrastructure.persistence.database.services import credential_service
from src.infrastructure.persistence.database.sql_database import (
    AgreementVersion,
    InviteCode,
    RegistrationRequest,
    User,
)
from src.web.http.types import RegisterRequest
from src.web.http.user_interface import UserInterface

UTC8 = timezone(timedelta(hours=8))
V1 = "terms-2026-10-v1"
V2 = "terms-2026-10-v2"
FIXED_NOW = datetime(2026, 10, 10, 14, 30, 25, tzinfo=UTC8)
INVITE = "INVITE-AAAA"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "ua2-test-secret")
    monkeypatch.setattr(credential_service, "_hash_password", lambda password: f"hash:{password}")
    monkeypatch.setattr(credential_service, "_verify_password", lambda password, stored: stored == f"hash:{password}")
    manager = DatabaseManager({"sql_db_folder": str(tmp_path / "db"), "sql_db_file": "ua2-web.db"})
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

    interface = UserInterface(manager, SimpleNamespace())
    monkeypatch.setattr(interface, "decrypt_user_password", lambda password: "plain-password")

    def service(current_version=V1):
        return RegistrationService(
            agreement_service=AgreementService(current_version, {}),
            credential_service=manager.credential_service,
            clock=lambda: FIXED_NOW,
        )

    return SimpleNamespace(manager=manager, interface=interface, service=service)


def body_of(response):
    """成功路径直接返回 dict，失败路径返回 JSONResponse：两种情况都归一成字典。"""
    if isinstance(response, dict):
        return response
    return json.loads(response.body)


def counts(env):
    session = env.manager.open_sql_session()
    try:
        return (
            session.query(User).count(),
            session.query(RegistrationRequest).count(),
            session.query(InviteCode).filter_by(code=INVITE).one().is_used,
        )
    finally:
        session.close()


def test_register_request_forbids_extra_fields():
    with pytest.raises(ValidationError):
        RegisterRequest(
            username="newbie",
            password="x",
            invite_code=INVITE,
            accepted_at="2026-10-10T14:30:25+08:00",
        )


def test_register_request_accepts_legacy_and_new_shapes():
    legacy = RegisterRequest(username="newbie", password="x", invite_code=INVITE)
    assert (legacy.registration_request_id, legacy.agreement_version, legacy.accepted) == (None, None, None)

    modern = RegisterRequest(
        username="newbie",
        password="x",
        invite_code=INVITE,
        registration_request_id="req-1",
        agreement_version=V1,
        accepted=True,
    )
    assert modern.accepted is True


@pytest.mark.asyncio
async def test_legacy_client_gets_403_with_code_and_no_side_effects(env):
    runtime = SimpleNamespace(registration_service=env.service())

    response = await env.interface.register(
        RegisterRequest(username="newbie", password="encrypted", invite_code=INVITE), runtime, None
    )

    assert response.status_code == 403
    body = body_of(response)
    assert body["code"] == "AGREEMENT_REQUIRED"
    assert "升级" in body["detail"]
    assert counts(env) == (0, 0, False)


@pytest.mark.asyncio
async def test_successful_registration_returns_legacy_success_payload(env):
    runtime = SimpleNamespace(registration_service=env.service())

    response = await env.interface.register(
        RegisterRequest(
            username="newbie",
            password="encrypted",
            invite_code=INVITE,
            registration_request_id="req-1",
            agreement_version=V1,
            accepted=True,
        ),
        runtime,
        None,
    )

    assert body_of(response) == {"message": "注册成功", "user_id": "newbie"}
    assert counts(env) == (1, 1, True)


@pytest.mark.asyncio
async def test_version_mismatch_returns_409_with_current_version(env):
    runtime = SimpleNamespace(registration_service=env.service(current_version=V2))

    response = await env.interface.register(
        RegisterRequest(
            username="newbie",
            password="encrypted",
            invite_code=INVITE,
            registration_request_id="req-1",
            agreement_version=V1,
            accepted=True,
        ),
        runtime,
        None,
    )

    assert response.status_code == 409
    body = body_of(response)
    assert body["code"] == "AGREEMENT_CHANGED"
    assert body["agreement_version"] == V2
    assert counts(env) == (0, 0, False)


@pytest.mark.asyncio
async def test_conflicting_request_id_returns_409_without_new_writes(env):
    runtime = SimpleNamespace(registration_service=env.service())
    payload = {
        "username": "newbie",
        "password": "encrypted",
        "invite_code": INVITE,
        "registration_request_id": "req-1",
        "agreement_version": V1,
        "accepted": True,
    }
    await env.interface.register(RegisterRequest(**payload), runtime, None)

    response = await env.interface.register(RegisterRequest(**{**payload, "username": "other"}), runtime, None)

    assert response.status_code == 409
    assert body_of(response)["code"] == "REGISTRATION_REQUEST_CONFLICT"
    assert counts(env) == (1, 1, True)


@pytest.mark.asyncio
async def test_invalid_invite_keeps_legacy_400_detail_only(env):
    runtime = SimpleNamespace(registration_service=env.service())

    response = await env.interface.register(
        RegisterRequest(
            username="newbie",
            password="encrypted",
            invite_code="NOT-FOUND",
            registration_request_id="req-1",
            agreement_version=V1,
            accepted=True,
        ),
        runtime,
        None,
    )

    assert response.status_code == 400
    assert body_of(response) == {"detail": "注册失败，请检查邀请码或用户名"}


@pytest.mark.asyncio
async def test_non_boolean_accepted_returns_422(env):
    runtime = SimpleNamespace(registration_service=env.service())

    response = await env.interface.register(
        RegisterRequest(
            username="newbie",
            password="encrypted",
            invite_code=INVITE,
            registration_request_id="req-1",
            agreement_version=V1,
            accepted=False,
        ),
        runtime,
        None,
    )

    assert response.status_code == 422
    assert body_of(response)["code"] == "INVALID_AGREEMENT_INPUT"
    assert counts(env) == (0, 0, False)
