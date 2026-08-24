import pytest

from src.message_process import message_processor as message_processor_module
from src.message_process.message_processor import MessageProcessor


@pytest.fixture
def processor():
    return MessageProcessor.__new__(MessageProcessor)


@pytest.fixture
def config(monkeypatch):
    modules = {
        "main_chat": {
            "enabled": True,
            "api_key": "sk-text",
            "model": "text-model",
            "base_url": "https://text.example/v1",
            "model_kind": "llm",
            "params": {"temperature": 0.2, "max_tokens": 2048},
            "model_capabilities": {
                "can_enable_thinking": True,
                "can_use_json": True,
            },
        },
        "image_understanding": {
            "enabled": True,
            "api_key": "sk-vlm",
            "model": "vision-model",
            "base_url": "https://vision.example/v1",
            "model_kind": "vlm",
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
            "type": "main_chat",
            "model_kind": "llm",
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
            "type": "image_understanding",
            "model_kind": "vlm",
            "image_base64": "data:image/png;base64,AAA",
        }
    )

    assert result["content"] == "image"
    assert captured["api_key"] == "sk-vlm"
    assert captured["payload"]["model"] == "vision-model"


@pytest.mark.asyncio
async def test_process_request_rejects_missing_json_capability(processor, config, monkeypatch):
    config["main_chat"]["model_capabilities"]["can_use_json"] = False
    captured = {}

    async def fake_call(**kwargs):
        captured.update(kwargs)
        return {"content": "ok", "usage": None}

    monkeypatch.setattr(message_processor_module, "call_llm_api_async", fake_call)
    result = await processor.process_llm_request(
        {
            "request_id": "req-json",
            "prompt": "hello",
            "type": "main_chat",
            "model_kind": "llm",
            "use_json": True,
            "enable_thinking": True,
        }
    )

    assert result["error"] == "当前客户端模型未声明 JSON 输出能力"
    assert captured == {}


@pytest.mark.asyncio
async def test_process_request_rejects_invalid_json_response(processor, config, monkeypatch):
    async def fake_call(**kwargs):
        return {"content": "not-json", "usage": None}

    monkeypatch.setattr(message_processor_module, "call_llm_api_async", fake_call)
    result = await processor.process_llm_request(
        {
            "request_id": "req-invalid-json",
            "prompt": "hello",
            "type": "main_chat",
            "model_kind": "llm",
            "use_json": True,
        }
    )
    assert result["error"] == "客户端模型未返回有效 JSON"


@pytest.mark.asyncio
async def test_process_request_rejects_model_kind_mismatch(processor, config, monkeypatch):
    called = {}

    async def fake_call(**kwargs):
        called.update(kwargs)
        return {"content": "ok", "usage": None}

    monkeypatch.setattr(message_processor_module, "call_llm_api_async", fake_call)
    result = await processor.process_llm_request(
        {
            "request_id": "req-kind",
            "prompt": "hello",
            "type": "main_chat",
            "model_kind": "vlm",
        }
    )
    assert "当前调用要求 VLM 模型" in result["error"]
    assert called == {}


@pytest.mark.asyncio
async def test_process_request_rejects_missing_thinking_capability(processor, config, monkeypatch):
    config["main_chat"]["model_capabilities"]["can_enable_thinking"] = False
    result = await processor.process_llm_request(
        {
            "request_id": "req-thinking",
            "prompt": "hello",
            "type": "main_chat",
            "model_kind": "llm",
            "enable_thinking": True,
        }
    )
    assert result["error"] == "当前客户端模型未声明 thinking 能力"


def test_get_llm_mode_reads_both_module_states(processor, config):
    assert processor.get_llm_mode() == {"types": ["main_chat", "image_understanding"]}


@pytest.mark.asyncio
async def test_process_request_reports_missing_type_key(processor, monkeypatch):
    monkeypatch.setattr(
        message_processor_module.llm_key_storage,
        "get_module_config",
        lambda key: {"enabled": True, "api_key": ""} if key == "image_understanding" else {
            "enabled": True,
            "api_key": "sk-text",
            "model": "text-model",
            "base_url": "https://text.example/v1",
        },
    )

    result = await processor.process_llm_request(
        {
            "request_id": "req-image",
            "type": "image_understanding",
            "model_kind": "vlm",
            "image_base64": "data:image/png;base64,AAA",
        }
    )

    assert result["error"] == "no api key configured on client"


@pytest.mark.asyncio
async def test_process_request_rejects_disabled_module(processor, config, monkeypatch):
    config["main_chat"]["enabled"] = False
    called = {}

    async def fake_call(**kwargs):
        called.update(kwargs)
        return {"content": "ok", "usage": None}

    monkeypatch.setattr(message_processor_module, "call_llm_api_async", fake_call)
    result = await processor.process_llm_request(
        {
            "request_id": "req-disabled",
            "prompt": "hello",
            "type": "main_chat",
            "model_kind": "llm",
        }
    )

    assert result == {
        "request_id": "req-disabled",
        "error": "no api key configured on client",
    }
    assert "url" not in called
