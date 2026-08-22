"""客户端模型类型配置（client_model_types）的校验与规范化测试。"""

import copy
import os
import sys
from pathlib import Path

import pytest

server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.system.admin.config_validator import RuntimeConfigValidator
from src.system.admin.llm_config_editor import apply_llm_config_draft
from src.system.admin.secret_store import SecretStore
from src.utils.helpers import load_config


@pytest.fixture(scope="module", autouse=True)
def server_cwd():
    old_cwd = os.getcwd()
    os.chdir(server_root)
    try:
        yield
    finally:
        os.chdir(old_cwd)


def _validator(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "jwt")
    monkeypatch.setenv("AMAP_KEY", "amap")
    return RuntimeConfigValidator(
        root_dir=tmp_path,
        secret_store=SecretStore(tmp_path / "secrets.local.env"),
    )


def _base_config():
    return load_config("config/config.json")


def _errors(result):
    return {
        item["name"]: item["message"]
        for item in result["items"]
        if item["status"] == "error"
    }


def _type_errors(result):
    errors = _errors(result)
    return {
        name: message
        for name, message in errors.items()
        if name.startswith("client_model_types") or name.startswith("binding.")
    }


def test_valid_client_model_types_passes(tmp_path, monkeypatch):
    validator = _validator(tmp_path, monkeypatch)
    result = validator.validate(_base_config())
    assert _type_errors(result) == {}


def test_client_model_types_ok_rows_present(tmp_path, monkeypatch):
    validator = _validator(tmp_path, monkeypatch)
    config = _base_config()
    result = validator.validate(config)
    ok_rows = {
        item["name"]: item["message"]
        for item in result["items"]
        if item["status"] == "ok"
        and (item["name"].startswith("client_model_types"))
    }
    assert "client_model_types" in ok_rows
    expected_count = len(
        [
            x
            for x in config["llm_service"]["client_model_types"]
            if isinstance(x, dict) and str(x.get("type") or "").strip()
        ]
    )
    assert f"已配置 {expected_count} 个客户端模型类型" in ok_rows["client_model_types"]
    type_rows = [
        (name, message)
        for name, message in ok_rows.items()
        if name.startswith("client_model_types.") and "已配置" in message
    ]
    assert len(type_rows) == expected_count


def test_missing_client_model_types_is_core_error(tmp_path, monkeypatch):
    config = _base_config()
    config["llm_service"].pop("client_model_types", None)
    result = _validator(tmp_path, monkeypatch).validate(config)
    assert "client_model_types" in _type_errors(result)


def test_empty_client_model_types_is_core_error(tmp_path, monkeypatch):
    config = _base_config()
    config["llm_service"]["client_model_types"] = []
    result = _validator(tmp_path, monkeypatch).validate(config)
    assert "client_model_types" in _type_errors(result)


def test_empty_type_name_is_error(tmp_path, monkeypatch):
    config = _base_config()
    config["llm_service"]["client_model_types"][0]["type"] = "   "
    result = _validator(tmp_path, monkeypatch).validate(config)
    assert any(
        name.startswith("client_model_types[") for name in _type_errors(result)
    )


def test_duplicate_type_name_is_error(tmp_path, monkeypatch):
    config = _base_config()
    first = copy.deepcopy(config["llm_service"]["client_model_types"][0])
    config["llm_service"]["client_model_types"].append(first)
    result = _validator(tmp_path, monkeypatch).validate(config)
    assert any(
        "重复" in message
        for message in _type_errors(result).values()
    )


def test_missing_provider_is_error(tmp_path, monkeypatch):
    config = _base_config()
    config["llm_service"]["client_model_types"][0]["providers"] = []
    result = _validator(tmp_path, monkeypatch).validate(config)
    assert any(
        "至少需要一个服务商" in message
        for message in _type_errors(result).values()
    )


def test_empty_provider_name_and_base_url_are_errors(tmp_path, monkeypatch):
    config = _base_config()
    provider = config["llm_service"]["client_model_types"][0]["providers"][0]
    provider["name"] = "  "
    provider["base_url"] = ""
    result = _validator(tmp_path, monkeypatch).validate(config)
    messages = list(_type_errors(result).values())
    assert any("服务商" in message and "缺少" in message for message in messages)
    assert any("base_url" in message for message in messages)


def test_duplicate_provider_name_is_error(tmp_path, monkeypatch):
    config = _base_config()
    provider = copy.deepcopy(
        config["llm_service"]["client_model_types"][0]["providers"][0]
    )
    config["llm_service"]["client_model_types"][0]["providers"].append(provider)
    result = _validator(tmp_path, monkeypatch).validate(config)
    assert any(
        "服务商名重复" in message
        for message in _type_errors(result).values()
    )


def test_empty_models_is_error(tmp_path, monkeypatch):
    config = _base_config()
    config["llm_service"]["client_model_types"][0]["providers"][0]["models"] = []
    result = _validator(tmp_path, monkeypatch).validate(config)
    assert any(
        "模型列表" in message
        for message in _type_errors(result).values()
    )


def test_empty_model_id_is_error(tmp_path, monkeypatch):
    config = _base_config()
    model = config["llm_service"]["client_model_types"][0]["providers"][0]["models"][0]
    model["id"] = "  "
    result = _validator(tmp_path, monkeypatch).validate(config)
    assert any(
        "模型 id 不能为空" in message
        for message in _type_errors(result).values()
    )


def test_duplicate_model_id_is_error(tmp_path, monkeypatch):
    config = _base_config()
    model = copy.deepcopy(
        config["llm_service"]["client_model_types"][0]["providers"][0]["models"][0]
    )
    config["llm_service"]["client_model_types"][0]["providers"][0]["models"].append(model)
    result = _validator(tmp_path, monkeypatch).validate(config)
    assert any(
        "模型 id 重复" in message
        for message in _type_errors(result).values()
    )


def test_binding_referencing_missing_type_is_error(tmp_path, monkeypatch):
    config = _base_config()
    config["database"]["event_store"]["llm_module"]["llm"][
        "client_model_type"
    ] = "不存在的类型"
    result = _validator(tmp_path, monkeypatch).validate(config)
    assert any(
        name.startswith("binding.") and "不存在的类型" in message
        for name, message in _type_errors(result).items()
    )


def test_apply_normalizes_client_model_types():
    payload = {
        "available_llms": {},
        "available_vlms": {},
        "module_bindings": [],
        "client_model_types": [
            {
                "type": "  对话模型  ",
                "description": "  填写说明  ",
                "providers": [
                    {
                        "name": " 服务商A ",
                        "base_url": "http://example.invalid/v1/",
                        "models": [
                            {"id": " a ", "can_enable_thinking": True},
                            {"id": "a"},
                            "b",
                        ],
                    },
                    {
                        "name": "服务商A",
                        "base_url": "http://x",
                        "models": [{"id": "c", "can_use_json": True}],
                    },
                ],
            },
            {"type": "对话模型", "providers": []},
        ],
    }
    next_config = apply_llm_config_draft({"llm_service": {}}, payload)
    types = next_config["llm_service"]["client_model_types"]
    assert len(types) == 1
    assert types[0]["type"] == "对话模型"
    assert types[0]["description"] == "填写说明"
    assert len(types[0]["providers"]) == 1
    provider = types[0]["providers"][0]
    assert provider["name"] == "服务商A"
    assert provider["base_url"] == "http://example.invalid/v1"
    assert [m["id"] for m in provider["models"]] == ["a", "b"]
    assert provider["models"][0]["can_enable_thinking"] is True
    assert provider["models"][0]["can_use_json"] is False
