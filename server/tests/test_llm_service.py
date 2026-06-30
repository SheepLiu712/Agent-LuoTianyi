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
        templates =  llm_service.prompt_manager.list_templates()
        assert len(templates) > 0, "PromptManager 应该加载至少一个模板"

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
