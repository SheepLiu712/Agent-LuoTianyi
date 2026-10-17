"""注册网络层：带上协议字段，并把服务端错误码解析出来（换版 / 冲突 / 升级）。"""

from types import SimpleNamespace

import pytest

from src.network import auth as auth_module
from src.network.auth import AuthApi, RegisterOutcome


class FakeResponse:
    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(
        auth_module.encrypt_pwd, "encrypt_password", lambda *a, **k: "ciphertext"
    )
    instance = AuthApi.__new__(AuthApi)
    instance.base_url = "https://example.invalid"
    instance.verify_ssl = True
    sent: list[dict] = []

    def post(url, json=None, **kwargs):
        sent.append({"url": url, "json": json})
        return instance._next_response

    instance.session = SimpleNamespace(post=post)
    instance.sent = sent
    return instance


def test_success_returns_outcome_without_code(api):
    api._next_response = FakeResponse(200, {"message": "注册成功", "user_id": "newbie"})

    outcome = api.register_with_agreement(
        "newbie",
        "pw",
        "INVITE",
        registration_request_id="req-1",
        agreement_version="v1",
        accepted=True,
    )

    assert outcome.ok is True
    assert outcome.code == ""
    assert api.sent[0]["json"] == {
        "username": "newbie",
        "password": "ciphertext",
        "invite_code": "INVITE",
        "registration_request_id": "req-1",
        "agreement_version": "v1",
        "accepted": True,
    }


def test_agreement_required_flat_envelope(api):
    api._next_response = FakeResponse(
        403,
        {
            "detail": "请升级到支持用户协议签署的版本，阅读并同意用户协议后再登录。",
            "code": "AGREEMENT_REQUIRED",
        },
    )

    outcome = api.register_with_agreement("newbie", "pw", "INVITE")

    assert outcome.ok is False
    assert outcome.code == "AGREEMENT_REQUIRED"
    assert "升级" in outcome.message


def test_agreement_changed_reports_current_version(api):
    api._next_response = FakeResponse(
        409,
        {
            "detail": "用户协议已更新，请重新阅读",
            "code": "AGREEMENT_CHANGED",
            "agreement_version": "terms-v2",
        },
    )

    outcome = api.register_with_agreement(
        "newbie",
        "pw",
        "INVITE",
        registration_request_id="req-1",
        agreement_version="v1",
        accepted=True,
    )

    assert outcome.code == "AGREEMENT_CHANGED"
    assert outcome.agreement_version == "terms-v2"


def test_request_conflict_code(api):
    api._next_response = FakeResponse(
        409,
        {
            "detail": "该注册请求与先前提交的内容不一致，请勿盲目重试",
            "code": "REGISTRATION_REQUEST_CONFLICT",
        },
    )

    outcome = api.register_with_agreement(
        "newbie",
        "pw",
        "INVITE",
        registration_request_id="req-1",
        agreement_version="v1",
        accepted=True,
    )

    assert outcome.code == "REGISTRATION_REQUEST_CONFLICT"


def test_nested_detail_envelope_is_understood(api):
    api._next_response = FakeResponse(
        403,
        {
            "detail": {
                "code": "AGREEMENT_REQUIRED",
                "message": "请先同意用户协议",
                "agreement_version": "v1",
            }
        },
    )

    outcome = api.register_with_agreement("newbie", "pw", "INVITE")

    assert outcome.code == "AGREEMENT_REQUIRED"
    assert outcome.message == "请先同意用户协议"
    assert outcome.agreement_version == "v1"


def test_invalid_invite_keeps_plain_detail(api):
    api._next_response = FakeResponse(400, {"detail": "注册失败，请检查邀请码或用户名"})

    outcome = api.register_with_agreement(
        "newbie",
        "pw",
        "BAD",
        registration_request_id="req-1",
        agreement_version="v1",
        accepted=True,
    )

    assert outcome.ok is False
    assert outcome.code == ""
    assert outcome.message == "注册失败，请检查邀请码或用户名"


def test_legacy_register_still_returns_tuple(api):
    api._next_response = FakeResponse(200, {"message": "注册成功"})

    assert api.register("newbie", "pw", "INVITE") == (True, "Registration Successful")
    assert "registration_request_id" not in api.sent[0]["json"]


def test_encryption_failure_returns_outcome(monkeypatch):
    monkeypatch.setattr(
        auth_module.encrypt_pwd, "encrypt_password", lambda *a, **k: None
    )
    instance = AuthApi.__new__(AuthApi)
    instance.base_url = "https://example.invalid"
    instance.verify_ssl = True
    instance.session = SimpleNamespace(post=lambda *a, **k: pytest.fail("不应发起请求"))

    outcome = instance.register_with_agreement("newbie", "pw", "INVITE")

    assert outcome == RegisterOutcome(
        False,
        "无法发送注册请求，请检查服务器连接后重试",
        code="REGISTRATION_NOT_SENT",
    )


def test_login_required_preserves_stable_agreement_error_details(api):
    api._next_response = FakeResponse(
        403,
        {
            "detail": "请升级到支持用户协议签署的版本，阅读并同意用户协议后再登录。",
            "code": "AGREEMENT_REQUIRED",
            "agreement_version": "terms-v2",
        },
    )
    ok, message, data = api.login("newbie", "pw")
    assert ok is False
    assert "升级" in message
    assert data == {
        "code": "AGREEMENT_REQUIRED",
        "agreement_version": "terms-v2",
        "status_code": 403,
    }


def test_accept_agreement_password_sends_only_protocol_credential(api, monkeypatch):
    monkeypatch.setattr(
        auth_module.encrypt_pwd, "encrypt_password", lambda *a, **k: "ciphertext"
    )
    api._next_response = FakeResponse(
        200,
        {"agreement_version": "terms-v1", "accepted_at": "2026-10-10T14:30:25+08:00"},
    )
    api.sent.clear()
    ok, message, data = api.accept_agreement("newbie", "terms-v1", password="pw")
    assert ok is True
    assert data["accepted_at"].endswith("+08:00")
    assert api.sent[-1]["url"].endswith("/auth/agreement/accept")
    assert api.sent[-1]["json"] == {
        "agreement_version": "terms-v1",
        "accepted": True,
        "credential": {
            "kind": "password",
            "username": "newbie",
            "password": "ciphertext",
        },
    }


def test_accept_agreement_auto_login_uses_token_without_password(api):
    api._next_response = FakeResponse(
        200,
        {"agreement_version": "terms-v1", "accepted_at": "2026-10-10T14:30:25+08:00"},
    )
    api.sent.clear()
    ok, _, _ = api.accept_agreement("newbie", "terms-v1", token="token")
    assert ok is True
    assert api.sent[-1]["json"]["credential"] == {
        "kind": "auto_login",
        "username": "newbie",
        "token": "token",
    }


def test_accept_agreement_reports_changed_version_and_identity_failure(api):
    api._next_response = FakeResponse(
        409,
        {
            "detail": "用户协议已更新，请重新阅读",
            "code": "AGREEMENT_CHANGED",
            "agreement_version": "v2",
        },
    )
    ok, message, data = api.accept_agreement("newbie", "v1", password="pw")
    assert (
        ok is False
        and data["code"] == "AGREEMENT_CHANGED"
        and data["agreement_version"] == "v2"
    )

    api._next_response = FakeResponse(401, {"detail": "身份验证失败"})
    ok, message, data = api.accept_agreement("newbie", "v1", password="pw")
    assert ok is False and data["status_code"] == 401 and data["code"] == ""


def test_login_and_auto_login_error_details_keep_legacy_shapes(api):
    api._next_response = FakeResponse(
        403, {"detail": "待签", "code": "AGREEMENT_REQUIRED", "agreement_version": "v1"}
    )
    login_ok, login_message, login_details = api.login("newbie", "pw")
    assert login_ok is False and login_details["code"] == "AGREEMENT_REQUIRED"

    api._next_response = FakeResponse(
        403, {"detail": "待签", "code": "AGREEMENT_REQUIRED", "agreement_version": "v1"}
    )
    auto_ok, auto_details = api.auto_login("newbie", "token")
    assert auto_ok is False and auto_details["code"] == "AGREEMENT_REQUIRED"
