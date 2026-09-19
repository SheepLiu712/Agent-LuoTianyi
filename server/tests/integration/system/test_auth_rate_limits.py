from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response

from src.system.user_interface import rate_limits


@pytest.fixture(autouse=True)
def clear_rate_limits():
    rate_limits._reset_rate_limit_state()
    yield
    rate_limits._reset_rate_limit_state()


def _request(ip: str):
    return SimpleNamespace(client=SimpleNamespace(host=ip))


def test_rotating_subjects_cannot_bypass_ip_limit():
    request = _request("203.0.113.10")
    for index in range(10):
        rate_limits.enforce_rate_limit(request, "auth_login", f"user-{index}")

    with pytest.raises(HTTPException) as exc_info:
        rate_limits.enforce_rate_limit(request, "auth_login", "another-user")

    assert exc_info.value.status_code == 429


def test_rotating_ips_cannot_bypass_subject_limit():
    for index in range(10):
        rate_limits.enforce_rate_limit(
            _request(f"203.0.113.{index + 20}"),
            "auth_login",
            "target-user",
        )

    with pytest.raises(HTTPException) as exc_info:
        rate_limits.enforce_rate_limit(
            _request("203.0.113.99"),
            "auth_login",
            "target-user",
        )

    assert exc_info.value.status_code == 429


def test_reset_limiter_keys_by_invite_credential_digest():
    request = _request("203.0.113.11")
    for _ in range(3):
        rate_limits.enforce_rate_limit(request, "auth_reset", "SECRET-INVITE-CODE")

    keys = list(rate_limits._rate_limit_store)
    assert all("SECRET-INVITE-CODE" not in key for key in keys)
    with pytest.raises(HTTPException):
        rate_limits.enforce_rate_limit(request, "auth_reset", "SECRET-INVITE-CODE")


def test_limiter_fails_closed_at_key_capacity(monkeypatch):
    monkeypatch.setattr(rate_limits, "_RATE_LIMIT_MAX_KEYS", 2)
    rate_limits.enforce_rate_limit(_request("203.0.113.12"), "auth_login", None)
    rate_limits.enforce_rate_limit(_request("203.0.113.13"), "auth_login", None)

    with pytest.raises(HTTPException) as exc_info:
        rate_limits.enforce_rate_limit(_request("203.0.113.14"), "auth_login", None)

    assert exc_info.value.status_code == 429


def test_admin_login_is_limited_across_rotating_ips():
    for index in range(5):
        rate_limits.enforce_rate_limit(
            _request(f"203.0.113.{index + 15}"),
            "admin_login",
            "admin",
        )

    with pytest.raises(HTTPException) as exc_info:
        rate_limits.enforce_rate_limit(
            _request("203.0.113.99"),
            "admin_login",
            "admin",
        )

    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
async def test_admin_login_endpoint_uses_stable_nonsecret_subject(monkeypatch):
    from src.system.admin import admin_interface

    calls = []

    def record_rate_limit(request, bucket, subject):
        calls.append((bucket, subject))

    class StubAuth:
        async def login_async(self, password, response):
            return {"ok": False}

    monkeypatch.setattr(admin_interface, "enforce_rate_limit", record_rate_limit)
    monkeypatch.setattr(
        admin_interface,
        "get_admin_shell",
        lambda: SimpleNamespace(auth=StubAuth()),
    )

    await admin_interface.admin_auth_login(
        _request("203.0.113.20"),
        Response(),
        {"password": "ADMIN-PASSWORD-MUST-NOT-BE-A-LIMITER-KEY"},
    )

    assert calls == [("admin_login", "admin")]
    assert "PASSWORD" not in repr(calls)
