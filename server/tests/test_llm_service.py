"""LLM Service 单元测试"""
import sys
import os
from pathlib import Path
import pytest
# 添加项目根目录
server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.utils.llm_service import LLMService
from src.utils.helpers import load_config


@pytest.fixture(scope="module", autouse=True)
def server_cwd():
    old_cwd = os.getcwd()
    os.chdir(server_root)
    try:
        yield
    finally:
        os.chdir(old_cwd)

@pytest.fixture(scope="function")
def llm_service():
    config = load_config("config/config.json")
    service = LLMService(config["llm_service"])
    return service

@pytest.fixture(scope="function")
def sample_template():
    template = {
    "name": "sample_template",
    "description": "用于测试的模板",
    "template": [
        "这是一个测试模板。",
        "你需要扮演名为 {{ character_name }} 的角色。",
        "请根据以下输入生成简洁的响应：",
        "{{ input_text }}"
    ]
}
    return template

class TestLLMService:
    def test_llm_service_registration(self, llm_service: LLMService):
        llm_interface_info = llm_service.get_llm_interface_info()
        assert isinstance(llm_interface_info, dict)
        assert len(llm_interface_info) > 0, "LLM接口信息应包含至少一个接口"
        for name, info in llm_interface_info.items():
            assert "type" in info, f"接口 {name} 缺少 'type' 字段"
            assert "model" in info, f"接口 {name} 缺少 'model' 字段"
            assert "base_url" in info, f"接口 {name} 缺少 'base_url' 字段"
            assert "temperature" in info, f"接口 {name} 缺少 'temperature' 字段"

        vlm_interface_info = llm_service.get_vlm_interface_info()
        assert isinstance(vlm_interface_info, dict)
        assert len(vlm_interface_info) > 0, "VLM接口信息应包含至少一个接口"
        for name, info in vlm_interface_info.items():
            assert "type" in info, f"接口 {name} 缺少 'type' 字段"
            assert "model" in info, f"接口 {name} 缺少 'model' 字段"
            assert "base_url" in info, f"接口 {name} 缺少 'base_url' 字段"
            assert "temperature" in info, f"接口 {name} 缺少 'temperature' 字段"

        assert llm_service.prompt_manager is not None, "PromptManager 应该被正确初始化"

    def test_get_client_model_types_dictionary(self, llm_service: LLMService):
        """客户端需求只包含类型和能力约束，不包含模型目录。"""
        types = llm_service.get_client_model_types()
        assert isinstance(types, list)
        assert len(types) > 0
        for type_item in types:
            assert type_item["id"]
            assert type_item["name"]
            assert isinstance(type_item.get("description"), str)
            assert type_item["model_kind"] in {"llm", "vlm"}
            assert isinstance(type_item["requires_json"], bool)
            assert isinstance(type_item["requires_thinking"], bool)
            assert "providers" not in type_item
            assert "models" not in type_item

    def test_client_model_types_match_config(self, llm_service: LLMService):
        """需求 ID、显示名与能力约束应从配置规范化透传。"""
        raw = (llm_service.config or {}).get("client_model_types") or []
        types = llm_service.get_client_model_types()
        assert len(types) == len([x for x in raw if isinstance(x, dict) and str(x.get("id") or "").strip()])
        raw_by_type = {
            str(x.get("id") or "").strip(): x
            for x in raw
            if isinstance(x, dict) and str(x.get("id") or "").strip()
        }
        for type_item in types:
            raw_type = raw_by_type[type_item["id"]]
            assert type_item["name"] == str(raw_type.get("name") or "").strip()
            assert type_item["description"] == str(raw_type.get("description") or "").strip()
            assert type_item["model_kind"] == str(raw_type.get("model_kind") or "").lower()
            assert type_item["requires_json"] == bool(raw_type.get("requires_json", False))

    def test_template_add_remove(self, llm_service: LLMService, sample_template, tmp_path):
        # 添加模板（从JSON数据）
        llm_service.prompt_manager.add_template_from_json(sample_template)
        templates = llm_service.prompt_manager.list_templates()
        assert sample_template["name"] in templates, "模板添加失败"

        # 移除模板
        removed = llm_service.prompt_manager.remove_template(sample_template["name"])
        assert removed, "模板移除失败"
        templates_after_removal = llm_service.prompt_manager.list_templates()
        assert sample_template["name"] not in templates_after_removal, "模板移除后仍存在"

        # 添加模板（从字符串）
        llm_service.prompt_manager.add_template_from_str(sample_template["name"], "\n".join(sample_template["template"]))
        templates_after_add_str = llm_service.prompt_manager.list_templates()
        assert sample_template["name"] in templates_after_add_str, "从字符串添加模板失败"
        removed = llm_service.prompt_manager.remove_template(sample_template["name"])
        assert removed, "模板移除失败"

        # 添加模板（从文件）
        temp_file_path = tmp_path / "temp_template.json"
        with open(temp_file_path, "w", encoding="utf-8") as f:
            import json
            json.dump(sample_template, f, ensure_ascii=False, indent=4)

        llm_service.prompt_manager.add_template_from_file(str(temp_file_path))
        templates_after_add_file = llm_service.prompt_manager.list_templates()
        assert sample_template["name"] in templates_after_add_file, "从文件添加模板失败"
        removed = llm_service.prompt_manager.remove_template(sample_template["name"])
        assert removed, "模板移除失败"

        # 移除不存在的模板
        removed_nonexistent = llm_service.prompt_manager.remove_template("nonexistent_template")
        assert not removed_nonexistent, "移除不存在的模板应该返回False"

    async def test_register_llm_module(self, llm_service: LLMService, sample_template):
        # 测试注册一个LLM模块
        llm_service.prompt_manager.add_template_from_json(sample_template)
        module_config = {
            "llm": {
                "name": list(llm_service.llm_interfaces.keys())[0],  # 使用第一个可用的LLM接口
                "enable_thinking": False,
            },
            "prompt_name": sample_template["name"]  # 使用第一个可用的模板
        }
        module_name = "test_llm_module"
        module = llm_service.register_llm_module(module_name, module_config)
        assert module.name == module_name, "注册的LLM模块名称不匹配"
        assert module.enable_thinking == False, "注册的LLM模块 enable_thinking 属性不匹配"

        vars = module.get_variables()
        assert "character_name" in vars, "模块变量中缺少 'character_name'"
        assert "input_text" in vars, "模块变量中缺少 'input_text'"

        resp = await module.generate_response(character_name="洛天依", input_text="你好，你是谁？")
        assert resp is not None, "生成的响应不应为None"
        recent_resp = module.recent_response
        assert recent_resp is not None, "最近一次的响应结果不应为None"
        token_usage = recent_resp.get("usage", {})
        assert "prompt_tokens" in token_usage and token_usage["prompt_tokens"] > 0, "最近一次响应的使用情况中缺少 'prompt_tokens'"
        assert "completion_tokens" in token_usage and token_usage["completion_tokens"] > 0, "最近一次响应的使用情况中缺少 'completion_tokens'"
        assert "total_tokens" in token_usage and token_usage["total_tokens"] > 0, "最近一次响应的使用情况中缺少 'total_tokens'"
        response_time_s = recent_resp.get("response_time_s", None)
        assert response_time_s is not None, "最近一次响应的使用情况中缺少 'response_time_s'"

    def test_register_llm_module_carries_client_model_type(
        self, llm_service: LLMService, sample_template
    ):
        """注册模块时应透传 client_model_type 与客户端执行器。"""
        llm_service.prompt_manager.add_template_from_json(sample_template)
        module_config = {
            "llm": {
                "name": list(llm_service.llm_interfaces.keys())[0],
                "enable_thinking": False,
                "use_json": True,
                "client_model_type": "对话模型",
            },
            "prompt_name": sample_template["name"],
        }
        module = llm_service.register_llm_module("test_delegated_module", module_config)
        assert module.client_model_type == "对话模型"
        assert module.client_llm_executor is None  # fixture 未注入执行器

        plain_config = {
            "llm": {
                "name": list(llm_service.llm_interfaces.keys())[0],
                "enable_thinking": False,
                "use_json": False,
            },
            "prompt_name": sample_template["name"],
        }
        plain_module = llm_service.register_llm_module("test_plain_module", plain_config)
        assert plain_module.client_model_type == ""
