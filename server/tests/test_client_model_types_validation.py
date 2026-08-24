"""客户端模型需求（client_model_types）的校验与规范化测试。"""

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


def _type_errors(result):
    return {
        item["name"]: item["message"]
        for item in result["items"]
        if item["status"] == "error"
        and (item["name"].startswith("client_model_types") or item["name"].startswith("binding."))
    }


def test_valid_client_model_types_passes(tmp_path, monkeypatch):
    assert _type_errors(_validator(tmp_path, monkeypatch).validate(_base_config())) == {}


def test_model_requirements_contain_no_provider_catalog():
    for item in _base_config()["llm_service"]["client_model_types"]:
        assert set(item) == {
            "id",
            "name",
            "description",
            "model_kind",
            "requires_json",
            "requires_thinking",
        }
        assert "providers" not in item


@pytest.mark.parametrize("value", [None, []])
def test_missing_or_empty_client_model_types_is_error(tmp_path, monkeypatch, value):
    config = _base_config()
    if value is None:
        config["llm_service"].pop("client_model_types", None)
    else:
        config["llm_service"]["client_model_types"] = value
    result = _validator(tmp_path, monkeypatch).validate(config)
    assert "client_model_types" in _type_errors(result)


def test_empty_and_duplicate_type_id_are_errors(tmp_path, monkeypatch):
    config = _base_config()
    duplicate = copy.deepcopy(config["llm_service"]["client_model_types"][0])
    config["llm_service"]["client_model_types"].append(duplicate)
    messages = _type_errors(_validator(tmp_path, monkeypatch).validate(config)).values()
    assert any("ID 重复" in message for message in messages)

    config = _base_config()
    config["llm_service"]["client_model_types"][0]["id"] = " "
    messages = _type_errors(_validator(tmp_path, monkeypatch).validate(config)).values()
    assert any("ID 不能为空" in message for message in messages)


def test_empty_display_name_and_invalid_kind_are_errors(tmp_path, monkeypatch):
    config = _base_config()
    config["llm_service"]["client_model_types"][0]["name"] = ""
    config["llm_service"]["client_model_types"][1]["model_kind"] = "audio"
    messages = _type_errors(_validator(tmp_path, monkeypatch).validate(config)).values()
    assert any("显示名称不能为空" in message for message in messages)
    assert any("llm 或 vlm" in message for message in messages)


def test_binding_referencing_missing_type_is_error(tmp_path, monkeypatch):
    config = _base_config()
    config["agent_runtime"]["agent"]["main_chat"]["llm_module"]["llm"]["client_model_type"] = "missing"
    messages = _type_errors(_validator(tmp_path, monkeypatch).validate(config)).values()
    assert any("missing" in message for message in messages)


def test_binding_kind_mismatch_is_error(tmp_path, monkeypatch):
    config = _base_config()
    config["capabilities"]["image_understanding"]["vlm_module"]["vlm"]["client_model_type"] = "main_chat"
    messages = _type_errors(_validator(tmp_path, monkeypatch).validate(config)).values()
    assert any("不能绑定到 vlm" in message for message in messages)


def test_binding_capability_mismatch_is_error(tmp_path, monkeypatch):
    config = _base_config()
    main = config["llm_service"]["client_model_types"][0]
    main["requires_json"] = False
    config["agent_runtime"]["agent"]["main_chat"]["llm_module"]["llm"]["use_json"] = True
    messages = _type_errors(_validator(tmp_path, monkeypatch).validate(config)).values()
    assert any("要求 JSON" in message for message in messages)


def test_apply_normalizes_requirements_and_drops_catalog_fields():
    payload = {
        "available_llms": {},
        "available_vlms": {},
        "module_bindings": [],
        "client_model_types": [
            {
                "id": "  main_chat  ",
                "name": " 主对话模型 ",
                "description": " 说明 ",
                "model_kind": "LLM",
                "requires_json": True,
                "requires_thinking": False,
                "providers": [{"name": "should be dropped"}],
            },
            {"id": "main_chat", "name": "duplicate", "model_kind": "vlm"},
        ],
    }
    next_config = apply_llm_config_draft({"llm_service": {}}, payload)
    assert next_config["llm_service"]["client_model_types"] == [
        {
            "id": "main_chat",
            "name": "主对话模型",
            "description": "说明",
            "model_kind": "llm",
            "requires_json": True,
            "requires_thinking": False,
        }
    ]
