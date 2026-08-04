"""credential 模块：LLM API Key 加密/明文保存行为测试。"""

import json

from src.safety import credential


def test_save_api_key_plaintext_when_encryption_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(credential, "_DPAPI_AVAILABLE", False)
    monkeypatch.setattr(
        credential, "get_credential_path", lambda: str(tmp_path / "user.json")
    )

    # 普通保存路径在加密不可用时返回 False 且不写入明文
    assert credential.save_api_key("sk-test") is False
    assert credential.get_api_key() is None
    # 显式明文保存（仅二次确认后可调用）
    credential.save_api_key_plain("sk-test")
    assert credential.get_api_key() == "sk-test"
    with open(tmp_path / "user.json", encoding="utf-8") as f:
        data = json.load(f)
    assert data.get("api_key_plain") == "sk-test"
    assert "api_key_dpapi" not in data


def test_save_api_key_refuses_plaintext_without_flag(monkeypatch, tmp_path):
    monkeypatch.setattr(credential, "_DPAPI_AVAILABLE", False)
    monkeypatch.setattr(
        credential, "get_credential_path", lambda: str(tmp_path / "user.json")
    )

    assert credential.save_api_key("sk-test") is False
    assert credential.get_api_key() is None
    if (tmp_path / "user.json").exists():
        data = json.loads((tmp_path / "user.json").read_text(encoding="utf-8"))
        assert "api_key_plain" not in data
        assert "api_key_dpapi" not in data


def test_save_api_key_clears_plaintext(monkeypatch, tmp_path):
    monkeypatch.setattr(credential, "_DPAPI_AVAILABLE", False)
    monkeypatch.setattr(
        credential, "get_credential_path", lambda: str(tmp_path / "user.json")
    )

    credential.save_api_key_plain("sk-test")
    assert credential.get_api_key() == "sk-test"
    assert credential.save_api_key("") is True
    assert credential.get_api_key() is None


def test_vlm_api_key_separate_from_text_key(monkeypatch, tmp_path):
    monkeypatch.setattr(credential, "_DPAPI_AVAILABLE", False)
    monkeypatch.setattr(credential, "get_credential_path", lambda: str(tmp_path / "user.json"))

    credential.save_api_key_plain("sk-text")
    credential.save_vlm_api_key_plain("sk-vlm")
    assert credential.get_api_key() == "sk-text"
    assert credential.get_vlm_api_key() == "sk-vlm"


def test_vlm_api_key_plaintext_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(credential, "_DPAPI_AVAILABLE", False)
    monkeypatch.setattr(credential, "get_credential_path", lambda: str(tmp_path / "user.json"))

    assert credential.save_vlm_api_key("sk-vlm", allow_plaintext=True) is True
    assert credential.get_vlm_api_key() == "sk-vlm"
