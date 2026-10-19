"""UA-2 注册用例：账号、协议签署、邀请码与注册请求结果必须在同一次提交里完成。"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from src.application.user import registration_service
from src.application.user.agreement_service import AgreementService, first_signed_at
from src.application.user.registration_service import (
    AgreementChangedError,
    AgreementRequiredError,
    InvalidAgreementInputError,
    RegistrationError,
    RegistrationRequestConflictError,
    RegistrationRequestUnverifiableError,
    RegistrationService,
)
from src.infrastructure.persistence.database.database_service import DatabaseManager
from src.infrastructure.persistence.database.services import credential_service
from src.infrastructure.persistence.database.sql_database import (
    AgreementSignature,
    AgreementVersion,
    InviteCode,
    RegistrationRequest,
    User,
)

UTC8 = timezone(timedelta(hours=8))
V1 = "terms-2026-10-v1"
V2 = "terms-2026-10-v2"
FIXED_NOW = datetime(2026, 10, 10, 14, 30, 25, 987654, tzinfo=UTC8)
INVITE = "INVITE-AAAA"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "ua2-test-secret")
    # 用廉价哈希替换 bcrypt，保持“哈希后校验”的语义但避免每个用例几百毫秒。
    monkeypatch.setattr(credential_service, "_hash_password", lambda password: f"hash:{password}")
    monkeypatch.setattr(credential_service, "_verify_password", lambda password, stored: stored == f"hash:{password}")
    manager = DatabaseManager({"sql_db_folder": str(tmp_path / "db"), "sql_db_file": "ua2.db"})

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

    def build(current_version=V1, clock=lambda: FIXED_NOW):
        return RegistrationService(
            agreement_service=AgreementService(current_version, {}),
            credential_service=manager.credential_service,
            clock=clock,
        )

    return SimpleNamespace(manager=manager, build=build)


def submit(service, **overrides):
    payload = {
        "username": "newbie",
        "password": "plain-password",
        "invite_code": INVITE,
        "registration_request_id": "req-1",
        "agreement_version": V1,
        "accepted": True,
    }
    payload.update(overrides)
    return service.register(**payload)


def snapshot(manager):
    session = manager.open_sql_session()
    try:
        return {
            "users": session.query(User).all(),
            "signatures": session.query(AgreementSignature).all(),
            "requests": session.query(RegistrationRequest).all(),
            "invite": session.query(InviteCode).filter_by(code=INVITE).one(),
        }
    finally:
        session.close()


def test_successful_registration_writes_account_signature_invite_and_result(env):
    result = submit(env.build())

    assert result == {"message": "注册成功", "user_id": "newbie"}
    state = snapshot(env.manager)
    assert [user.username for user in state["users"]] == ["newbie"]
    assert state["invite"].is_used is True
    assert state["invite"].user_id == state["users"][0].uuid
    assert [(row.agreement_version, row.accepted_at) for row in state["signatures"]] == [
        (V1, "2026-10-10T14:30:25+08:00")
    ]
    assert [row.registration_request_id for row in state["requests"]] == ["req-1"]
    assert first_signed_at(session_of(env), state["users"][0].uuid, V1) == "2026-10-10T14:30:25+08:00"


def session_of(env):
    return env.manager.open_sql_session()


def test_repeated_same_request_returns_original_result_without_new_writes(env):
    service = env.build()
    first = submit(service)

    later = env.build(clock=lambda: datetime(2026, 10, 11, 9, 0, 0, tzinfo=UTC8))
    second = submit(later)

    assert second == first
    state = snapshot(env.manager)
    assert len(state["users"]) == 1
    assert len(state["signatures"]) == 1
    assert len(state["requests"]) == 1
    assert state["signatures"][0].accepted_at == "2026-10-10T14:30:25+08:00"


def test_replaying_a_successful_v1_request_still_succeeds_after_v2_is_published(env):
    submit(env.build(current_version=V1))

    # 部署已启用 V2，但原 V1 请求确实成功过：必须恢复原结果，而不是报换版。
    replayed = submit(env.build(current_version=V2))

    assert replayed == {"message": "注册成功", "user_id": "newbie"}


def test_unfinished_request_against_new_version_is_rejected_without_side_effects(env):
    with pytest.raises(AgreementChangedError) as caught:
        submit(env.build(current_version=V2))

    assert caught.value.current_version == V2
    assert caught.value.status_code == 409
    state = snapshot(env.manager)
    assert state["users"] == []
    assert state["signatures"] == []
    assert state["requests"] == []
    assert state["invite"].is_used is False


def test_same_request_id_with_different_username_conflicts(env):
    submit(env.build())

    with pytest.raises(RegistrationRequestConflictError):
        submit(env.build(), username="someone-else")

    assert len(snapshot(env.manager)["users"]) == 1


def test_same_request_id_with_different_invite_code_conflicts(env):
    session = env.manager.open_sql_session()
    try:
        session.add(InviteCode(code="INVITE-BBBB", is_used=False, disabled=False))
        session.commit()
    finally:
        session.close()
    submit(env.build())

    with pytest.raises(RegistrationRequestConflictError):
        submit(env.build(), invite_code="INVITE-BBBB")


def test_same_request_id_with_unverifiable_password_is_not_treated_as_success(env):
    submit(env.build())

    with pytest.raises(RegistrationRequestUnverifiableError):
        submit(env.build(), password="wrong-password")


def test_legacy_client_without_agreement_fields_is_rejected_without_side_effects(env):
    with pytest.raises(AgreementRequiredError) as caught:
        submit(env.build(), registration_request_id=None, agreement_version=None, accepted=None)

    assert caught.value.status_code == 403
    assert "升级" in caught.value.detail
    state = snapshot(env.manager)
    assert state["users"] == []
    assert state["invite"].is_used is False


@pytest.mark.parametrize("accepted", [False, "true", 1, None])
def test_non_strict_accepted_value_is_rejected(env, accepted):
    kwargs = {"accepted": accepted}
    if accepted is None:
        kwargs["agreement_version"] = None
    with pytest.raises((InvalidAgreementInputError, AgreementRequiredError)):
        submit(env.build(), **kwargs)

    assert snapshot(env.manager)["users"] == []


def test_missing_request_id_is_invalid_input(env):
    with pytest.raises(InvalidAgreementInputError):
        submit(env.build(), registration_request_id="")


def test_invalid_invite_code_leaves_no_account_signature_or_request_row(env):
    with pytest.raises(RegistrationError) as caught:
        submit(env.build(), invite_code="NOT-FOUND")

    assert caught.value.status_code == 400
    state = snapshot(env.manager)
    assert state["users"] == []
    assert state["signatures"] == []
    assert state["requests"] == []
    assert state["invite"].is_used is False


def test_failure_after_claiming_invite_rolls_back_every_write(env, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("signature write failed")

    monkeypatch.setattr(registration_service, "record_signature", boom)

    with pytest.raises(RuntimeError):
        submit(env.build())

    state = snapshot(env.manager)
    assert state["users"] == []
    assert state["signatures"] == []
    assert state["requests"] == []
    assert state["invite"].is_used is False


def test_same_request_id_race_replays_the_committed_result(env, monkeypatch):
    service = env.build()
    first = submit(service, registration_request_id="req-race")
    original_replay = service._replay
    calls = 0

    def hide_first_replay(db, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return None
        return original_replay(db, **kwargs)

    monkeypatch.setattr(service, "_replay", hide_first_replay)
    second = submit(service, registration_request_id="req-race")

    assert second == first
    assert calls == 2
    state = snapshot(env.manager)
    assert len(state["users"]) == 1
    assert len(state["signatures"]) == 1
    assert len(state["requests"]) == 1
    assert state["invite"].is_used is True


def test_concurrent_same_request_id_unique_violation_replays_committed_result(env, monkeypatch):
    """另一方已提交、本事务撞唯一约束时，应返回原成功结果而不是抛 IntegrityError（HTTP 500）。"""
    service = env.build()
    first = submit(service, registration_request_id="req-race-500")

    calls = 0
    original_replay = service._replay

    def hide_first_replay(db, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return None
        return original_replay(db, **kwargs)

    def fail_with_unique_violation(*args, **kwargs):
        raise IntegrityError("UNIQUE constraint failed: users.username", None, None)

    monkeypatch.setattr(service, "_replay", hide_first_replay)
    monkeypatch.setattr(service._credentials, "create_account_with_invite", fail_with_unique_violation)

    second = submit(service, registration_request_id="req-race-500")

    assert second == first
    state = snapshot(env.manager)
    assert len(state["users"]) == 1
    assert len(state["signatures"]) == 1
    assert len(state["requests"]) == 1


def test_two_requests_competing_for_one_invite_code_leave_exactly_one_account(env):
    service = env.build()
    submit(service)

    with pytest.raises(RegistrationError):
        submit(env.build(), username="second", registration_request_id="req-2")

    state = snapshot(env.manager)
    assert [user.username for user in state["users"]] == ["newbie"]
    assert state["invite"].user_id == state["users"][0].uuid


def test_accepted_time_uses_injected_clock_and_second_precision(env):
    clock = lambda: datetime(2026, 12, 31, 23, 59, 59, 999999, tzinfo=timezone.utc)  # noqa: E731
    submit(env.build(clock=clock))

    row = snapshot(env.manager)["signatures"][0]
    assert row.accepted_at == "2027-01-01T07:59:59+08:00"
