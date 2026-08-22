"""credential 模块：凭据本地存储行为测试。"""

import json

from src.safety import credential, crypto


def _setup(monkeypatch, tmp_path):
    """关闭 DPAPI，把凭据文件指到临时目录。"""
    monkeypatch.setattr(crypto, "_BACKEND", None)
    monkeypatch.setattr(
        credential, "get_credential_path", lambda: str(tmp_path / "user.json")
    )


def test_save_credentials_preserves_server_url(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    credential.save_server_url("https://srv", verify_ssl=True)
    credential.save_credentials("u", "", False)
    assert credential.get_server_url() == "https://srv"


def test_save_credentials_preserves_unknown_fields(monkeypatch, tmp_path):
    """save_credentials 保留文件内所有非凭据字段，不做白名单裁剪。"""
    _setup(monkeypatch, tmp_path)
    path = tmp_path / "user.json"
    path.write_text(
        json.dumps(
            {
                "username": "old",
                "custom_field": {"a": 1},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    credential.save_credentials("new", "", False)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["username"] == "new"
    assert data["auto_login"] is False
    assert data["custom_field"] == {"a": 1}


def test_save_credentials_logout_clears_token(monkeypatch, tmp_path):
    """登出（token 为空）时清除已存的 token，且不影响其他字段。"""
    _setup(monkeypatch, tmp_path)
    path = tmp_path / "user.json"
    path.write_text(
        json.dumps(
            {
                "username": "u",
                "token_dpapi": "c2VjcmV0",
                "auto_login": True,
                "server_url": "https://srv",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    credential.save_credentials("u", "", False)

    username, token, auto_login, _ = credential.load_credentials()
    assert username == "u"
    assert token is None
    assert auto_login is False
    data = json.loads((tmp_path / "user.json").read_text(encoding="utf-8"))
    assert "token_dpapi" not in data
    assert "token" not in data
    assert data["server_url"] == "https://srv"


