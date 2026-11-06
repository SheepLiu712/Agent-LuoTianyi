import queue
import threading

import pytest

from src.message_process import message_processor as message_processor_module
from src.message_process.message_processor import MessageProcessor, PreparedAgentMessage


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
    assert processor.get_llm_mode() == {"types": ["main_chat", "image_understanding"], "stream": True}


@pytest.mark.asyncio
async def test_stream_request_keeps_client_configuration_and_forwards_deltas(processor, config, monkeypatch):
    captured, deltas = {}, []

    async def receive(text):
        deltas.append(text)

    async def fake_call(**kwargs):
        captured.update(kwargs)
        await kwargs["on_delta"]("第一句话。")
        return {"content": "第一句话。", "usage": {"total_tokens": 4}}

    monkeypatch.setattr(message_processor_module, "call_llm_api_async", fake_call)
    result = await processor.process_llm_request(
        {"request_id": "stream-1", "type": "main_chat", "prompt": "你好", "stream": True}, on_delta=receive
    )
    assert captured["payload"]["stream"] is True
    assert captured["payload"]["model"] == "text-model"
    assert captured["api_key"] == "sk-text"
    assert deltas == ["第一句话。"]
    assert result["content"] == "第一句话。"


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


class _RecordingLogger:
    def __init__(self):
        self.errors = []

    def error(self, message, *args, **kwargs):
        self.errors.append(message)


def _bare_processor():
    processor = MessageProcessor.__new__(MessageProcessor)
    processor._running = True
    processor._event_queue = queue.Queue()
    processor._playback_queue = queue.Queue()
    processor.logger = _RecordingLogger()
    return processor


def test_listener_thread_survives_poison_message():
    processor = _bare_processor()
    prepared_payloads = []

    def prepare(payload):
        if payload == "poison":
            raise RuntimeError("prepare boom")
        prepared_payloads.append(payload)
        return PreparedAgentMessage(response=payload, audio_saved=False)

    processor._prepare_agent_message = prepare
    thread = threading.Thread(target=processor._listen_ws_events, daemon=True)
    thread.start()
    processor._event_queue.put("poison")
    processor._event_queue.put("good")
    processor._event_queue.put(None)
    thread.join(timeout=3)

    assert not thread.is_alive()
    assert prepared_payloads == ["good"]
    assert processor._playback_queue.get(timeout=1).response == "good"
    assert processor._playback_queue.get(timeout=1) is None
    assert processor.logger.errors, "预处理异常必须被记录"


def test_playback_thread_survives_poison_message():
    processor = _bare_processor()
    processed = []

    def process(response, audio_saved=False):
        if response == "poison":
            raise RuntimeError("playback boom")
        processed.append(response)

    processor.process_transport_message = process
    thread = threading.Thread(target=processor._process_playback_events, daemon=True)
    thread.start()
    processor._playback_queue.put(PreparedAgentMessage(response="poison"))
    processor._playback_queue.put(PreparedAgentMessage(response="good"))
    processor._playback_queue.put(None)
    thread.join(timeout=3)

    assert not thread.is_alive()
    assert processed == ["good"]
    assert processor.logger.errors, "展示/播放异常必须被记录"
