"""后台签署必须成功后才续接原登录，取消和失败不得产生登录副作用。"""

from contextlib import nullcontext
from threading import Event
from unittest.mock import Mock

import pytest
from src.network import auth


@pytest.mark.parametrize("automatic", [False, True])
@pytest.mark.parametrize("acceptance", ["success", "changed", "cancelled"])
def test_signing_continues_only_the_original_login(monkeypatch, automatic, acceptance):
    cancelled = Event()
    calls = []
    api = Mock()
    details = {"user_id": "test", "token": "business-token"}

    def accept(*args, **kwargs):
        calls.append(("accept", args, kwargs))
        if acceptance == "cancelled":
            cancelled.set()
        if acceptance == "changed":
            return False, "协议已更新", {"code": "AGREEMENT_CHANGED"}
        return True, "", {}

    def login(*args):
        calls.append(("login", args))
        return True, "登录成功", details

    def auto_login(*args):
        calls.append(("auto_login", args))
        return True, details

    api.accept_agreement.side_effect = accept
    api.login.side_effect = login
    api.auto_login.side_effect = auto_login
    session = object()
    monkeypatch.setattr(auth.HttpClientFactory, "create_session", lambda: nullcontext(session))
    factory = Mock(return_value=api)
    monkeypatch.setattr(auth, "AuthApi", factory)
    request = auth.AccountRequest(
        context=(),
        action="agreement_login",
        base_url="https://test.invalid",
        username="test",
        password="password",
        remember=True,
        agreement_version="v2",
        token="remember-token" if automatic else None,
    )

    outcome = request.execute(cancelled)

    factory.assert_called_once_with("https://test.invalid", session=session, cancelled=cancelled)
    assert calls[0] == (
        "accept",
        ("test", "v2"),
        {"password": None if automatic else "password", "token": "remember-token" if automatic else None},
    )
    if acceptance == "success":
        assert outcome == (True, "登录成功", details)
        expected = ("auto_login", ("test", "remember-token")) if automatic else ("login", ("test", "password", True))
        assert calls[1:] == [expected]
    else:
        assert len(calls) == 1
        assert not outcome[0]
        if acceptance == "changed":
            assert outcome[2]["code"] == "AGREEMENT_CHANGED"
