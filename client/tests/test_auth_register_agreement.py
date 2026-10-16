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
    monkeypatch.setattr(auth_module.encrypt_pwd, "encrypt_password", lambda *a, **k: "ciphertext")
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
        "newbie", "pw", "INVITE", registration_request_id="req-1", agreement_version="v1", accepted=True
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
        403, {"detail": "请升级到支持用户协议签署的版本，阅读并同意用户协议后再登录。", "code": "AGREEMENT_REQUIRED"}
    )

    outcome = api.register_with_agreement("newbie", "pw", "INVITE")

    assert outcome.ok is False
    assert outcome.code == "AGREEMENT_REQUIRED"
    assert "升级" in outcome.message


def test_agreement_changed_reports_current_version(api):
    api._next_response = FakeResponse(
        409,
        {"detail": "用户协议已更新，请重新阅读", "code": "AGREEMENT_CHANGED", "agreement_version": "terms-v2"},
    )

    outcome = api.register_with_agreement(
        "newbie", "pw", "INVITE", registration_request_id="req-1", agreement_version="v1", accepted=True
    )

    assert outcome.code == "AGREEMENT_CHANGED"
    assert outcome.agreement_version == "terms-v2"


def test_request_conflict_code(api):
    api._next_response = FakeResponse(
        409, {"detail": "该注册请求与先前提交的内容不一致，请勿盲目重试", "code": "REGISTRATION_REQUEST_CONFLICT"}
    )

    outcome = api.register_with_agreement(
        "newbie", "pw", "INVITE", registration_request_id="req-1", agreement_version="v1", accepted=True
    )

    assert outcome.code == "REGISTRATION_REQUEST_CONFLICT"


def test_nested_detail_envelope_is_understood(api):
    api._next_response = FakeResponse(
        403, {"detail": {"code": "AGREEMENT_REQUIRED", "message": "请先同意用户协议", "agreement_version": "v1"}}
    )

    outcome = api.register_with_agreement("newbie", "pw", "INVITE")

    assert outcome.code == "AGREEMENT_REQUIRED"
    assert outcome.message == "请先同意用户协议"
    assert outcome.agreement_version == "v1"


def test_invalid_invite_keeps_plain_detail(api):
    api._next_response = FakeResponse(400, {"detail": "注册失败，请检查邀请码或用户名"})

    outcome = api.register_with_agreement(
        "newbie", "pw", "BAD", registration_request_id="req-1", agreement_version="v1", accepted=True
    )

    assert outcome.ok is False
    assert outcome.code == ""
    assert outcome.message == "注册失败，请检查邀请码或用户名"


def test_legacy_register_still_returns_tuple(api):
    api._next_response = FakeResponse(200, {"message": "注册成功"})

    assert api.register("newbie", "pw", "INVITE") == (True, "Registration Successful")
    assert "registration_request_id" not in api.sent[0]["json"]


def test_encryption_failure_returns_outcome(monkeypatch):
    monkeypatch.setattr(auth_module.encrypt_pwd, "encrypt_password", lambda *a, **k: None)
    instance = AuthApi.__new__(AuthApi)
    instance.base_url = "https://example.invalid"
    instance.verify_ssl = True
    instance.session = SimpleNamespace(post=lambda *a, **k: pytest.fail("不应发起请求"))

    outcome = instance.register_with_agreement("newbie", "pw", "INVITE")

    assert outcome == RegisterOutcome(False, "Failed to encrypt password. Check server connection.")
