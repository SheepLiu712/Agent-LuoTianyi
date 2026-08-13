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

    def test_get_client_providers_derived_from_interfaces(self, llm_service: LLMService):
        """服务商列表应由 LLM/VLM 接口配置拼接，且每个服务商至少在一种能力下可用。"""
        providers = llm_service.get_client_providers()
        assert isinstance(providers, list)
        assert len(providers) > 0

        by_name = {}
        for provider in providers:
            assert provider["name"]
            assert provider["base_url"]
            assert isinstance(provider["llm_models"], list)
            assert isinstance(provider["vlm_models"], list)
            assert "models" not in provider
            assert provider["llm_models"] or provider["vlm_models"]
            by_name[provider["name"]] = provider

        # LLM 接口的 model 应出现在对应服务商的 llm_models 中
        llm_info = llm_service.get_llm_interface_info()
        for name, info in llm_info.items():
            assert info["model"] in by_name[name]["llm_models"]
        # VLM 接口的 model 应出现在对应服务商的 vlm_models 中
        vlm_info = llm_service.get_vlm_interface_info()
        for name, info in vlm_info.items():
            assert info["model"] in by_name[name]["vlm_models"]

    def test_model_capabilities_from_interfaces(self, llm_service: LLMService):
        """模型能力标注应由接口配置的 can_* 字段下发，作为客户端唯一能力来源。"""
        llm_caps = llm_service.get_llm_model_capabilities()
        vlm_caps = llm_service.get_vlm_model_capabilities()
        assert llm_caps
        assert vlm_caps
        for caps in (*llm_caps.values(), *vlm_caps.values()):
            assert "can_enable_thinking" in caps
            assert "can_use_json" in caps
        cfg = llm_service.config
        for entry in (cfg.get("available_llms") or {}).values():
            if isinstance(entry, dict) and entry.get("model"):
                assert llm_caps[entry["model"]]["can_use_json"] == bool(
                    entry.get("can_use_json", False)
                )
        for entry in (cfg.get("available_vlms") or {}).values():
            if isinstance(entry, dict) and entry.get("model"):
                assert vlm_caps[entry["model"]]["can_enable_thinking"] == bool(
                    entry.get("can_enable_thinking", False)
                )
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

    def test_register_llm_module_tracks_json_label(self, llm_service: LLMService, sample_template):
        """需要 JSON 输出的模块应记录配置中的友好标签，供客户端保存提示使用。"""
        llm_service.prompt_manager.add_template_from_json(sample_template)
        module_config = {
            "label": "测试模块",
            "llm": {
                "name": list(llm_service.llm_interfaces.keys())[0],
                "enable_thinking": False,
                "use_json": True,
            },
            "prompt_name": sample_template["name"],
        }
        llm_service.register_llm_module("test_json_module", module_config)
        assert llm_service.get_llm_json_required_modules() == [
            {"name": "test_json_module", "label": "测试模块"}
        ]

        # 未开启 use_json 的模块不应进入列表
        plain_config = {
            "label": "普通模块",
            "llm": {
                "name": list(llm_service.llm_interfaces.keys())[0],
                "enable_thinking": False,
                "use_json": False,
            },
            "prompt_name": sample_template["name"],
        }
        llm_service.register_llm_module("test_plain_module", plain_config)
        names = [m["name"] for m in llm_service.get_llm_json_required_modules()]
        assert "test_plain_module" not in names

        # 未配置 label 时回退到模块名
        no_label_config = dict(module_config)
        no_label_config.pop("label", None)
        llm_service.register_llm_module("test_no_label_module", no_label_config)
        labels = {m["name"]: m["label"] for m in llm_service.get_llm_json_required_modules()}
        assert labels["test_no_label_module"] == "test_no_label_module"
