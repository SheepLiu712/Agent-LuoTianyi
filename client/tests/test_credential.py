"""credential 模块：统一 LLM 模块配置（llm_modules）加密/明文保存行为测试。"""

import json

from src.safety import credential


def _setup(monkeypatch, tmp_path):
    """关闭 DPAPI，把凭据文件指到临时目录：与旧测试同一套隔离方式。"""
    monkeypatch.setattr(credential, "_DPAPI_AVAILABLE", False)
    monkeypatch.setattr(
        credential, "get_credential_path", lambda: str(tmp_path / "user.json")
    )


def test_get_llm_modules_config_empty_default(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    assert credential.get_llm_modules_config() == {}
    assert credential.get_module_config("llm_models") is None


def test_save_llm_modules_config_plaintext_roundtrip(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    modules = {
        "llm_models": {
            "enabled": True,
            "provider": "DeepSeek",
            "model": "deepseek-v4-flash",
            "base_url": "https://api.deepseek.com/v1",
            "params": {"temperature": 0.7},
            "api_key": "sk-test",
        },
        "vlm_models": {
            "enabled": False,
            "provider": "",
            "model": "",
            "base_url": "",
            "params": {},
            "api_key": "",
        },
    }
    assert credential.save_llm_modules_config(modules, allow_plaintext=True) is True

    cfg = credential.get_llm_modules_config()
    assert cfg["llm_models"]["enabled"] is True
    assert cfg["llm_models"]["api_key"] == "sk-test"
    assert cfg["llm_models"]["provider"] == "DeepSeek"
    assert cfg["llm_models"]["model"] == "deepseek-v4-flash"
    assert cfg["llm_models"]["base_url"] == "https://api.deepseek.com/v1"
    assert cfg["llm_models"]["params"] == {"temperature": 0.7}
    assert cfg["vlm_models"]["enabled"] is False
    assert cfg["vlm_models"]["api_key"] == ""
    assert credential.get_module_config("llm_models")["api_key"] == "sk-test"

    with open(tmp_path / "user.json", encoding="utf-8") as f:
        data = json.load(f)
    stored = data["llm_modules"]["llm_models"]
    assert stored["api_key_plain"] == "sk-test"
    assert "api_key_dpapi" not in stored


def test_save_llm_modules_config_refuses_plaintext_without_flag(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    modules = {
        "llm_models": {
            "enabled": True,
            "provider": "P",
            "model": "M",
            "base_url": "B",
            "params": {},
            "api_key": "sk-test",
        }
    }
    assert credential.save_llm_modules_config(modules) is False
    if (tmp_path / "user.json").exists():
        data = json.loads((tmp_path / "user.json").read_text(encoding="utf-8"))
        assert "llm_modules" not in data or not data["llm_modules"]


def test_save_llm_modules_config_preserves_other_fields(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    path = tmp_path / "user.json"
    path.write_text(
        json.dumps(
            {
                "username": "user1",
                "server_url": "https://srv",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assert credential.save_llm_modules_config(
        {
            "llm_models": {
                "enabled": True,
                "provider": "P",
                "model": "M",
                "base_url": "B",
                "params": {},
                "api_key": "sk2",
            }
        },
        allow_plaintext=True,
    ) is True

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["username"] == "user1"
    assert data["server_url"] == "https://srv"
    assert credential.load_credentials()[0] == "user1"


def test_save_credentials_preserves_server_url(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    credential.save_server_url("https://srv", verify_ssl=True)
    credential.save_credentials("u", "", False)
    assert credential.get_server_url() == "https://srv"


def test_model_capabilities_roundtrip_in_module_config(monkeypatch, tmp_path):
    """所选模型的能力支持随模块配置原子写入并可读回。"""
    _setup(monkeypatch, tmp_path)
    credential.save_server_url("https://srv", verify_ssl=True)
    assert (
        credential.save_llm_modules_config(
            {
                "llm_models": {
                    "enabled": True,
                    "provider": "P",
                    "model": "M",
                    "base_url": "B",
                    "params": {},
                    "model_capabilities": {
                        "can_enable_thinking": True,
                        "can_use_json": False,
                    },
                    "api_key": "",
                }
            }
        )
        is True
    )
    saved = credential.get_llm_modules_config()["llm_models"]
    assert saved["provider"] == "P"
    assert saved["model_capabilities"] == {
        "can_enable_thinking": True,
        "can_use_json": False,
    }
    assert credential.get_server_url() == "https://srv"
