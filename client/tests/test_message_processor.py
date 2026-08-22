import pytest

from src.message_process import message_processor as message_processor_module
from src.message_process.message_processor import MessageProcessor


@pytest.fixture
def processor():
    return MessageProcessor.__new__(MessageProcessor)


@pytest.fixture
def config(monkeypatch):
    modules = {
        "对话模型": {
            "enabled": True,
            "api_key": "sk-text",
            "model": "text-model",
            "base_url": "https://text.example/v1",
            "params": {"temperature": 0.2, "max_tokens": 2048},
            "model_capabilities": {
                "can_enable_thinking": True,
                "can_use_json": True,
            },
        },
        "图片理解模型": {
            "enabled": True,
            "api_key": "sk-vlm",
            "model": "vision-model",
            "base_url": "https://vision.example/v1",
            "params": {},
            "model_capabilities": {
                "can_enable_thinking": False,
                "can_use_json": False,
            },
        },
    }
    monkeypatch.setattr(
        message_processor_module.llm_key_storage,
        "get_module_config",
        modules.get,
    )
    monkeypatch.setattr(
        message_processor_module.llm_key_storage,
        "get_llm_modules_config",
        lambda: modules,
    )
    return modules


@pytest.mark.asyncio
async def test_process_text_request_uses_saved_config_and_merges_params(processor, config, monkeypatch):
    captured = {}

    async def fake_call(**kwargs):
        captured.update(kwargs)
        return {"content": "ok", "usage": {"total_tokens": 3}}

    monkeypatch.setattr(message_processor_module, "call_llm_api_async", fake_call)
    result = await processor.process_llm_request(
        {
            "request_id": "req-1",
            "prompt": "hello",
            "type": "对话模型",
            "params": {"temperature": 0.9, "top_p": 0.5},
        }
    )

    assert result == {"request_id": "req-1", "content": "ok", "usage": {"total_tokens": 3}}
    assert captured["url"] == "https://text.example/v1/chat/completions"
    assert captured["api_key"] == "sk-text"
    assert captured["payload"]["model"] == "text-model"
    assert captured["payload"]["temperature"] == 0.2
    assert captured["payload"]["top_p"] == 0.5


@pytest.mark.asyncio
async def test_process_image_request_uses_type_config(processor, config, monkeypatch):
    captured = {}

    async def fake_call(**kwargs):
        captured.update(kwargs)
        return {"content": "image", "usage": None}

    monkeypatch.setattr(message_processor_module, "call_llm_api_async", fake_call)
    result = await processor.process_llm_request(
        {
            "request_id": "req-image",
            "prompt": "describe",
            "type": "图片理解模型",
            "image_base64": "data:image/png;base64,AAA",
        }
    )

    assert result["content"] == "image"
    assert captured["api_key"] == "sk-vlm"
    assert captured["payload"]["model"] == "vision-model"


@pytest.mark.asyncio
async def test_process_request_gates_json_by_capability(processor, config, monkeypatch):
    config["对话模型"]["model_capabilities"]["can_use_json"] = False
    captured = {}

    async def fake_call(**kwargs):
        captured.update(kwargs)
        return {"content": "ok", "usage": None}

    monkeypatch.setattr(message_processor_module, "call_llm_api_async", fake_call)
    result = await processor.process_llm_request(
        {
            "request_id": "req-json",
            "prompt": "hello",
            "type": "对话模型",
            "use_json": True,
            "enable_thinking": True,
        }
    )

    assert result["content"] == "ok"
    assert "response_format" not in captured["payload"]
    assert "enable_thinking" in captured["payload"]


def test_get_llm_mode_reads_both_module_states(processor, config):
    assert processor.get_llm_mode() == {"types": ["对话模型", "图片理解模型"]}


@pytest.mark.asyncio
async def test_process_request_reports_missing_type_key(processor, monkeypatch):
    monkeypatch.setattr(
        message_processor_module.llm_key_storage,
        "get_module_config",
        lambda key: {"enabled": True, "api_key": ""} if key == "图片理解模型" else {
            "enabled": True,
            "api_key": "sk-text",
            "model": "text-model",
            "base_url": "https://text.example/v1",
        },
    )

    result = await processor.process_llm_request(
        {
            "request_id": "req-image",
            "type": "图片理解模型",
            "image_base64": "data:image/png;base64,AAA",
        }
    )

    assert result["error"] == "no api key configured on client"
