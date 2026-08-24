"""utils.llm_key_storage：LLM 模块配置（用户配置，非凭据）加密/明文保存行为测试。"""

import json

from src.safety import credential, crypto
from src.utils import llm_key_storage


def _setup(monkeypatch, tmp_path):
    """关闭 DPAPI，把 LLM 配置文件与凭据文件指到临时目录。"""
    monkeypatch.setattr(crypto, "_BACKEND", None)
    monkeypatch.setattr(
        credential, "get_credential_path", lambda: str(tmp_path / "user.json")
    )
    monkeypatch.setattr(
        llm_key_storage,
        "get_llm_modules_path",
        lambda: str(tmp_path / "llm_modules.json"),
    )


def test_get_llm_modules_config_empty_default(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    assert llm_key_storage.get_llm_modules_config() == {}
    assert llm_key_storage.get_module_config("对话模型") is None


def test_save_llm_modules_config_plaintext_roundtrip(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    modules = {
        "对话模型": {
            "enabled": True,
            "provider": "DeepSeek",
            "model": "deepseek-v4-flash",
            "base_url": "https://api.deepseek.com/v1",
            "params": {"temperature": 0.7},
            "api_key": "sk-test",
        },
        "图片理解模型": {
            "enabled": False,
            "provider": "",
            "model": "",
            "base_url": "",
            "params": {},
            "api_key": "",
        },
    }
    assert llm_key_storage.save_llm_modules_config(modules, allow_plaintext=True) is True

    cfg = llm_key_storage.get_llm_modules_config()
    assert cfg["对话模型"]["enabled"] is True
    assert cfg["对话模型"]["api_key"] == "sk-test"
    assert cfg["对话模型"]["provider"] == "DeepSeek"
    assert cfg["对话模型"]["model"] == "deepseek-v4-flash"
    assert cfg["对话模型"]["base_url"] == "https://api.deepseek.com/v1"
    assert cfg["对话模型"]["params"] == {"temperature": 0.7}
    assert cfg["图片理解模型"]["enabled"] is False
    assert cfg["图片理解模型"]["api_key"] == ""
    assert llm_key_storage.get_module_config("对话模型")["api_key"] == "sk-test"

    with open(tmp_path / "llm_modules.json", encoding="utf-8") as f:
        data = json.load(f)
    stored = data["对话模型"]
    assert stored["api_key_plain"] == "sk-test"
    assert "api_key_dpapi" not in stored


def test_save_llm_modules_config_refuses_plaintext_without_flag(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    modules = {
        "对话模型": {
            "enabled": True,
            "provider": "P",
            "model": "M",
            "base_url": "B",
            "params": {},
            "api_key": "sk-test",
        }
    }
    assert llm_key_storage.save_llm_modules_config(modules) is False
    llm_path = tmp_path / "llm_modules.json"
    if llm_path.exists():
        data = json.loads(llm_path.read_text(encoding="utf-8"))
        assert data == {}


def test_save_llm_modules_config_preserves_other_fields(monkeypatch, tmp_path):
    """保存 LLM 配置只写 llm_modules.json，不触碰 user.json。"""
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
    assert llm_key_storage.save_llm_modules_config(
        {
            "对话模型": {
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
    assert "llm_modules" not in data
    llm_data = json.loads(
        (tmp_path / "llm_modules.json").read_text(encoding="utf-8")
    )
    assert llm_data["对话模型"]["api_key_plain"] == "sk2"
    assert credential.load_credentials()[0] == "user1"
    assert credential.get_server_url() == "https://srv"


def test_save_credentials_does_not_touch_llm_config(monkeypatch, tmp_path):
    """保存凭据只写 user.json，不触碰 llm_modules.json（用户配置与凭据隔离）。"""
    _setup(monkeypatch, tmp_path)
    assert llm_key_storage.save_llm_modules_config(
        {
            "对话模型": {
                "enabled": True,
                "provider": "DeepSeek",
                "model": "deepseek-v4-flash",
                "base_url": "https://api.deepseek.com/v1",
                "params": {"temperature": 0.7},
                "api_key": "sk-test",
            }
        },
        allow_plaintext=True,
    ) is True

    credential.save_credentials("user1", "", False)

    cfg = llm_key_storage.get_llm_modules_config()
    assert cfg["对话模型"]["api_key"] == "sk-test"
    assert cfg["对话模型"]["provider"] == "DeepSeek"
    assert credential.load_credentials()[0] == "user1"
    user_data = json.loads((tmp_path / "user.json").read_text(encoding="utf-8"))
    assert "llm_modules" not in user_data


def test_model_capabilities_roundtrip_in_module_config(monkeypatch, tmp_path):
    """所选模型的能力支持随模块配置原子写入并可读回。"""
    _setup(monkeypatch, tmp_path)
    credential.save_server_url("https://srv", verify_ssl=True)
    assert (
        llm_key_storage.save_llm_modules_config(
            {
                "对话模型": {
                    "enabled": True,
                    "provider": "P",
                    "model": "M",
                    "base_url": "B",
                    "model_kind": "llm",
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
    saved = llm_key_storage.get_llm_modules_config()["对话模型"]
    assert saved["provider"] == "P"
    assert saved["model_capabilities"] == {
        "can_enable_thinking": True,
        "can_use_json": False,
    }
    assert saved["model_kind"] == "llm"
    assert credential.get_server_url() == "https://srv"


def test_corrupt_llm_file_isolated_from_credentials(monkeypatch, tmp_path):
    """LLM 配置文件损坏不影响凭据读写，凭据写入也不覆盖损坏的 LLM 文件。"""
    _setup(monkeypatch, tmp_path)
    llm_path = tmp_path / "llm_modules.json"
    llm_path.write_text("{corrupt", encoding="utf-8")
    (tmp_path / "user.json").write_text(
        json.dumps({"username": "u", "server_url": "https://srv"}, ensure_ascii=False),
        encoding="utf-8",
    )

    assert llm_key_storage.get_llm_modules_config() == {}
    assert credential.load_credentials()[0] == "u"

    credential.save_credentials("u2", "", False)
    assert credential.load_credentials()[0] == "u2"
    assert llm_path.read_text(encoding="utf-8") == "{corrupt"
