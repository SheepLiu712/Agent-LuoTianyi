import pytest

from src.message_process import message_processor as message_processor_module
from src.message_process.message_processor import MessageProcessor


@pytest.fixture
def processor():
    return MessageProcessor.__new__(MessageProcessor)


@pytest.fixture
def config(monkeypatch):
    modules = {
        "llm_models": {
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
        "vlm_models": {
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
    monkeypatch.setattr(message_processor_module.credential, "get_module_config", modules.get)
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
            "provider": {"model": "server-model"},
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
async def test_process_image_request_uses_vlm_config(processor, config, monkeypatch):
    captured = {}

    async def fake_call(**kwargs):
        captured.update(kwargs)
        return {"content": "image", "usage": None}

    monkeypatch.setattr(message_processor_module, "call_llm_api_async", fake_call)
    result = await processor.process_llm_request(
        {
            "request_id": "req-image",
            "prompt": "describe",
            "image_base64": "data:image/png;base64,AAA",
        }
    )

    assert result["content"] == "image"
    assert captured["api_key"] == "sk-vlm"
    assert captured["payload"]["model"] == "vision-model"


@pytest.mark.asyncio
async def test_process_request_rejects_unsupported_json(processor, config, monkeypatch):
    config["llm_models"]["model_capabilities"]["can_use_json"] = False
    monkeypatch.setattr(message_processor_module, "call_llm_api_async", pytest.fail)

    result = await processor.process_llm_request(
        {"request_id": "req-json", "prompt": "hello", "use_json": True}
    )

    assert result["error"] == message_processor_module.CLIENT_JSON_UNSUPPORTED_MARKER


def test_get_llm_mode_reads_both_module_states(processor, config):
    assert processor.get_llm_mode() == {"text": True, "vlm": True}


@pytest.mark.asyncio
async def test_process_request_reports_missing_vlm_key(processor, monkeypatch):
    monkeypatch.setattr(
        message_processor_module.credential,
        "get_module_config",
        lambda key: {"enabled": True, "api_key": ""} if key == "vlm_models" else {
            "enabled": True,
            "api_key": "sk-text",
            "model": "text-model",
            "base_url": "https://text.example/v1",
        },
    )

    result = await processor.process_llm_request(
        {"request_id": "req-image", "image_base64": "data:image/png;base64,AAA"}
    )

    assert result["error"] == "no api key configured on client"