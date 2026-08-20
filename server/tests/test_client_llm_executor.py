"""ClientLLMExecutor 与 LLMModule/VLMModule 客户端委托的单元测试。"""

import asyncio
import inspect
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# 添加项目根目录
server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.utils.llm.client_llm_executor import (
    ClientLLMError,
    ClientLLMExecutor,
    ClientLLMTimeout,
    ClientLLMUnavailable,
    _looks_like_key_error,
)
from src.chat_session.chat_stream_manager import ChatStreamManager
from src.utils.llm.llm_api_interface import LLMAPIInterface
from src.utils.llm.llm_module import LLMModule
from src.utils.llm_service import LLMService
from src.utils.vision.vlm_api_interface import VLMAPIInterface
from src.utils.vision.vlm_module import VLMModule


class FakeWebSocket:
    def __init__(self):
        self.sent_events = []

    async def send_json(self, event):
        self.sent_events.append(event)


class FakeStream:
    def __init__(self, websocket, client_mode=None):
        self.ws_connection = self._as_connection(websocket, client_mode)

    def is_connection_lost(self):
        return False

    def lost_connection(self, ws_connection=None):
        if ws_connection is not None and self.ws_connection is not ws_connection:
            return False
        if self.ws_connection is None:
            return False
        self.ws_connection = None
        return True

    def reconnect(self, websocket, client_mode=None):
        self.ws_connection = self._as_connection(websocket, client_mode)

    @staticmethod
    def _as_connection(websocket, client_mode=None):
        if hasattr(websocket, "websocket"):
            websocket.client_mode = dict(
                client_mode
                or getattr(websocket, "client_mode", None)
                or {"types": []}
            )
            return websocket
        return SimpleNamespace(
            websocket=websocket,
            client_mode=dict(client_mode or {"types": []}),
        )


class FakeStreamManager:
    def __init__(self, stream=None):
        self.stream = stream

    def get_stream_by_user_uuid(self, user_id):
        return self.stream


class FakeDelegateExecutor:
    """记录 delegate 调用，可配置返回结果或抛错。"""

    _DEFAULT_RESULT = {
        "content": "client-answer",
        "usage": {},
        "response_time_s": 0.1,
    }

    def __init__(self, result=_DEFAULT_RESULT, error=None):
        self.result = result
        self.error = error
        self.calls = []

    async def delegate(self, user_id, **kwargs):
        self.calls.append((user_id, kwargs))
        if self.error is not None:
            raise self.error
        return self.result


class FakeInner:
    default_parameters = {}

    def __init__(self):
        self.calls = 0

    def get_interface_info(self):
        return {"type": "fake", "model": "x", "base_url": "http://fake"}

    async def generate_response(
        self,
        prompt,
        params=None,
        enable_thinking=False,
        use_json=False,
        **kwargs,
    ):
        self.calls += 1
        return {"content": "inner-answer", "usage": None, "response_time_s": 0.1}


class FakeVLMInner:
    default_parameters = {}

    def __init__(self):
        self.calls = 0

    def get_interface_info(self):
        return {"type": "fake", "model": "x", "base_url": "http://fake"}

    async def generate_response(self, prompt, image_base64=None, **kwargs):
        self.calls += 1
        return {"content": "inner-vlm-answer", "usage": {}, "response_time_s": 0.1}


class FakePromptTemplate:
    def __init__(self, variables=("character_name", "input_text")):
        self._variables = list(variables)

    def render(self, **kwargs):
        return f"prompt:{kwargs}"

    def get_variables(self):
        return self._variables


@pytest.fixture
def executor():
    return ClientLLMExecutor(timeout_seconds=1.0)


@pytest.fixture
def fake_ws():
    return FakeWebSocket()


def test_on_llm_response_is_sync():
    assert not inspect.iscoroutinefunction(ClientLLMExecutor.on_llm_response)


def test_error_classification():
    assert _looks_like_key_error("LLM provider returned HTTP 401: invalid api key") is True
    assert _looks_like_key_error("HTTP 403 Access denied") is True
    assert _looks_like_key_error("connection refused") is False


def test_is_enabled_checks_types_membership(executor, fake_ws):
    executor.bind(FakeStreamManager(FakeStream(fake_ws, client_mode={"types": ["对话模型"]})))
    assert executor.is_enabled("u1", "对话模型") is True
    assert executor.is_enabled("u1", "图片理解模型") is False
    assert executor.is_enabled("u1", "") is False
    executor.bind(FakeStreamManager(FakeStream(fake_ws, client_mode={"types": []})))
    assert executor.is_enabled("u1", "对话模型") is False
    executor.bind(FakeStreamManager(None))
    assert executor.is_enabled("u1", "对话模型") is False


def test_multi_connection_mode_follows_active_connection(executor):
    device_a_ws = FakeWebSocket()
    device_b_ws = FakeWebSocket()
    stream = FakeStream(device_a_ws, client_mode={"types": ["对话模型"]})
    executor.bind(FakeStreamManager(stream))
    assert executor.is_enabled("u1", "对话模型") is True

    stream.reconnect(device_b_ws, client_mode={"types": []})
    assert executor.is_enabled("u1", "对话模型") is False

    stream.reconnect(device_b_ws, client_mode={"types": ["对话模型"]})
    assert executor.is_enabled("u1", "对话模型") is True


@pytest.mark.asyncio
async def test_delegate_returns_none_when_not_configured_or_disabled(executor, fake_ws):
    executor.bind(FakeStreamManager(FakeStream(fake_ws, client_mode={"types": []})))
    assert await executor.delegate(
        "u1", module="m", model_type="", prompt="p", params=None
    ) is None
    assert await executor.delegate(
        "u1", module="m", model_type="对话模型", prompt="p", params=None
    ) is None

    executor.bind(FakeStreamManager(None))
    assert await executor.delegate(
        "u1", module="m", model_type="对话模型", prompt="p", params=None
    ) is None
    assert fake_ws.sent_events == []


@pytest.mark.asyncio
async def test_delegate_sends_type_payload_without_provider(executor, fake_ws):
    executor.bind(
        FakeStreamManager(FakeStream(fake_ws, client_mode={"types": ["对话模型"]}))
    )
    task = asyncio.create_task(
        executor.delegate(
            "u1",
            module="main_chat",
            model_type="对话模型",
            prompt="hello",
            params={"temperature": 0.7},
            enable_thinking=True,
            use_json=True,
        )
    )
    await asyncio.sleep(0)
    assert len(fake_ws.sent_events) == 1
    event = fake_ws.sent_events[0]
    assert event["type"] == "llm_request"
    payload = event["payload"]
    assert payload["module"] == "main_chat"
    assert payload["type"] == "对话模型"
    assert payload["prompt"] == "hello"
    assert payload["params"] == {"temperature": 0.7}
    assert payload["enable_thinking"] is True
    assert payload["use_json"] is True
    assert "provider" not in payload
    assert "image_base64" not in payload

    request_id = payload["request_id"]
    executor.on_llm_response(
        {"request_id": request_id, "content": "ok", "usage": None}
    )
    result = await task
    assert result["content"] == "ok"


@pytest.mark.asyncio
async def test_delegate_includes_image_base64(executor, fake_ws):
    executor.bind(
        FakeStreamManager(FakeStream(fake_ws, client_mode={"types": ["图片理解模型"]}))
    )
    task = asyncio.create_task(
        executor.delegate(
            "u1",
            module="image_understanding",
            model_type="图片理解模型",
            prompt="describe",
            params=None,
            image_base64="data:image/png;base64,AAA",
        )
    )
    await asyncio.sleep(0)
    payload = fake_ws.sent_events[0]["payload"]
    assert payload["type"] == "图片理解模型"
    assert payload["image_base64"] == "data:image/png;base64,AAA"
    request_id = payload["request_id"]
    executor.on_llm_response(
        {"request_id": request_id, "content": "desc", "usage": None}
    )
    result = await task
    assert result["content"] == "desc"


@pytest.mark.asyncio
async def test_delegate_error_raises_without_fallback(executor, fake_ws):
    executor.bind(
        FakeStreamManager(FakeStream(fake_ws, client_mode={"types": ["对话模型"]}))
    )
    task = asyncio.create_task(
        executor.delegate(
            "u1", module="m", model_type="对话模型", prompt="p", params=None
        )
    )
    await asyncio.sleep(0)
    request_id = fake_ws.sent_events[0]["payload"]["request_id"]
    executor.on_llm_response({"request_id": request_id, "error": "HTTP 401 bad key"})
    with pytest.raises(ClientLLMError):
        await task


@pytest.mark.asyncio
async def test_delegate_timeout(executor, fake_ws):
    executor.bind(
        FakeStreamManager(FakeStream(fake_ws, client_mode={"types": ["对话模型"]}))
    )
    with pytest.raises(ClientLLMTimeout):
        await executor.delegate(
            "u1", module="m", model_type="对话模型", prompt="p", params=None
        )


@pytest.mark.asyncio
async def test_delegate_send_failure_raises_unavailable(executor):
    class BrokenWebSocket:
        async def send_json(self, event):
            raise RuntimeError("socket closed")

    executor.bind(
        FakeStreamManager(FakeStream(BrokenWebSocket(), client_mode={"types": ["对话模型"]}))
    )
    with pytest.raises(ClientLLMUnavailable):
        await executor.delegate(
            "u1", module="m", model_type="对话模型", prompt="p", params=None
        )


@pytest.mark.asyncio
async def test_clear_user_fails_pending(executor, fake_ws):
    stream = FakeStream(fake_ws, client_mode={"types": ["对话模型"]})
    executor.bind(FakeStreamManager(stream))
    task = asyncio.create_task(
        executor.delegate(
            "u1", module="m", model_type="对话模型", prompt="p", params=None
        )
    )
    await asyncio.sleep(0)
    executor.clear_user("u1", stream.ws_connection)
    with pytest.raises(ClientLLMUnavailable):
        await task


def test_ws_lost_connection_ignores_stale_connection():
    manager = ChatStreamManager({}, None, None, None, None)
    device_a = SimpleNamespace(websocket=FakeWebSocket(), user_uuid="u1")
    stream = FakeStream(device_a, client_mode={"types": ["对话模型"]})
    manager.user_streams[("u1", "luotianyi")] = stream

    device_b = SimpleNamespace(websocket=FakeWebSocket(), user_uuid="u1")
    stream.reconnect(device_b, client_mode={"types": []})
    assert manager.ws_lost_connection(device_a) is False
    assert stream.ws_connection is device_b

    assert manager.ws_lost_connection(device_b) is True
    assert stream.ws_connection is None


@pytest.mark.asyncio
async def test_llm_module_delegates_when_type_configured():
    executor = FakeDelegateExecutor()
    inner = FakeInner()
    module = LLMModule(
        "m",
        {"name": "x", "client_model_type": "对话模型"},
        FakePromptTemplate(),
        inner,
        client_llm_executor=executor,
    )
    result = await module.generate_response(character_name="洛天依", input_text="你好")
    assert result == "client-answer"
    assert len(executor.calls) == 1
    _, kwargs = executor.calls[0]
    assert kwargs["model_type"] == "对话模型"
    assert kwargs["module"] == "m"
    assert inner.calls == 0


@pytest.mark.asyncio
async def test_llm_module_direct_connect_when_type_empty():
    executor = FakeDelegateExecutor()
    inner = FakeInner()
    module = LLMModule(
        "m",
        {"name": "x"},
        FakePromptTemplate(),
        inner,
        client_llm_executor=executor,
    )
    result = await module.generate_response(character_name="洛天依", input_text="你好")
    assert result == "inner-answer"
    assert executor.calls == []
    assert inner.calls == 1


@pytest.mark.asyncio
async def test_llm_module_delegate_none_falls_back_to_inner():
    executor = FakeDelegateExecutor(result=None)
    inner = FakeInner()
    module = LLMModule(
        "m",
        {"name": "x", "client_model_type": "对话模型"},
        FakePromptTemplate(),
        inner,
        client_llm_executor=executor,
    )
    result = await module.generate_response(character_name="洛天依", input_text="你好")
    assert result == "inner-answer"
    assert inner.calls == 1


@pytest.mark.asyncio
async def test_vlm_module_delegates_with_image():
    executor = FakeDelegateExecutor()
    inner = FakeVLMInner()
    module = VLMModule(
        "v",
        {"vlm": {"name": "x", "client_model_type": "图片理解模型"}},
        FakePromptTemplate(),
        inner,
        client_llm_executor=executor,
    )
    result = await module.generate_response(
        image_base64="data:image/png;base64,AAA",
        user_text="这是什么",
    )
    assert result["content"] == "client-answer"
    _, kwargs = executor.calls[0]
    assert kwargs["model_type"] == "图片理解模型"
    assert kwargs["image_base64"] == "data:image/png;base64,AAA"
    assert inner.calls == 0


@pytest.mark.asyncio
async def test_vlm_module_direct_connect_when_type_empty():
    executor = FakeDelegateExecutor()
    inner = FakeVLMInner()
    module = VLMModule(
        "v",
        {"vlm": {"name": "x"}},
        FakePromptTemplate(),
        inner,
        client_llm_executor=executor,
    )
    result = await module.generate_response(
        image_base64="data:image/png;base64,AAA",
        user_text="这是什么",
    )
    assert result["content"] == "inner-vlm-answer"
    assert executor.calls == []
    assert inner.calls == 1


def test_llm_service_does_not_wrap_interfaces(monkeypatch):
    monkeypatch.setattr(
        "src.utils.llm_service.LLMAPIFactory.create_interface",
        staticmethod(lambda config: FakeInner()),
    )
    monkeypatch.setattr(
        "src.utils.llm_service.VLMAPIFactory.create_interface",
        staticmethod(lambda config: FakeVLMInner()),
    )
    service = LLMService(
        {
            "available_llms": {"a": {}},
            "available_vlms": {"v": {}},
            "client_model_types": [],
        },
        client_llm_executor=ClientLLMExecutor(),
    )
    assert isinstance(service.llm_interfaces["a"], FakeInner)
    assert isinstance(service.vlm_interfaces["v"], FakeVLMInner)
    assert not hasattr(service.llm_interfaces["a"], "delegate")


def test_llm_service_interfaces_are_llm_vlm_types(monkeypatch):
    monkeypatch.setattr(
        "src.utils.llm_service.LLMAPIFactory.create_interface",
        staticmethod(lambda config: FakeInner()),
    )
    monkeypatch.setattr(
        "src.utils.llm_service.VLMAPIFactory.create_interface",
        staticmethod(lambda config: FakeVLMInner()),
    )
    service = LLMService({"available_llms": {"a": {}}, "available_vlms": {"v": {}}})
    assert isinstance(service.llm_interfaces["a"], LLMAPIInterface) or isinstance(
        service.llm_interfaces["a"], FakeInner
    )
    assert isinstance(service.vlm_interfaces["v"], VLMAPIInterface) or isinstance(
        service.vlm_interfaces["v"], FakeVLMInner
    )
