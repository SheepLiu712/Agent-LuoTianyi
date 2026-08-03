"""ClientLLMExecutor 与 ClientDelegatingLLM/VLMInterface 的单元测试。"""

import asyncio
import inspect
from types import SimpleNamespace

import pytest

from src.utils.llm.client_delegating_interface import (
    ClientDelegatingLLMInterface,
    ClientDelegatingVLMInterface,
)
from src.utils.llm.client_llm_executor import (
    ClientLLMError,
    ClientLLMExecutor,
    ClientLLMTimeout,
    ClientLLMUnavailable,
)
from src.utils.llm.llm_api_interface import LLMAPIInterface
from src.utils.llm_service import LLMService
from src.utils.vision.vlm_api_interface import VLMAPIInterface


class FakeWebSocket:
    def __init__(self):
        self.sent_events = []

    async def send_json(self, event):
        self.sent_events.append(event)


class FakeStream:
    def __init__(self, websocket):
        self.ws_connection = SimpleNamespace(websocket=websocket)

    def is_connection_lost(self):
        return False


class FakeStreamManager:
    def __init__(self, stream=None):
        self.stream = stream

    def get_stream_by_user_uuid(self, user_id):
        return self.stream


def test_on_llm_response_is_sync():
    """on_llm_response 是同步回调，server_main 中不能用 await 调用。"""
    assert not inspect.iscoroutinefunction(ClientLLMExecutor.on_llm_response)


class FakeInner(LLMAPIInterface):
    default_parameters = {"temperature": 0.7}

    def __init__(self):
        self.calls = []
        self.config = {
            "api_type": "openai",
            "base_url": "https://example.com/v1",
            "model": "test-model",
            "api_key": "sk-should-never-leak",
            "can_enable_thinking": True,
            "can_use_json": True,
        }

    async def generate_response(
        self,
        prompt,
        params=None,
        enable_thinking=False,
        use_json=False,
        **kwargs,
    ):
        self.calls.append((prompt, params, enable_thinking, use_json))
        return {"content": "server-answer", "usage": None, "response_time_s": 0.1}

    def set_parameters(self, **params):
        pass

    def get_interface_info(self):
        return {
            "type": "FakeInner",
            "model": self.config["model"],
            "base_url": self.config["base_url"],
        }


class FakeVLMInner(VLMAPIInterface):
    def __init__(self):
        self.calls = []
        self.config = {
            "api_type": "openai",
            "base_url": "https://example.com/v1",
            "model": "test-vlm",
            "api_key": "sk-should-never-leak",
        }

    async def generate_response(self, prompt, image_base64, **kwargs):
        self.calls.append((prompt, image_base64, kwargs))
        return {"content": "vlm-answer", "usage": None, "response_time_s": 0.1}

    def set_parameters(self, **params):
        pass

    def get_interface_info(self):
        return {
            "type": "FakeVLMInner",
            "model": self.config["model"],
            "base_url": self.config["base_url"],
        }


@pytest.fixture
def executor():
    return ClientLLMExecutor(timeout_seconds=5.0)


@pytest.fixture
def fake_ws():
    return FakeWebSocket()


@pytest.mark.asyncio
async def test_request_response_correlation(executor, fake_ws):
    executor.bind(FakeStreamManager(FakeStream(fake_ws)))
    executor.set_llm_mode("u1", True)

    task = asyncio.create_task(
        executor.request("u1", module="main_chat", prompt="hello", params={"temperature": 0.7})
    )
    await asyncio.sleep(0)

    assert fake_ws.sent_events
    payload = fake_ws.sent_events[0]["payload"]
    assert payload["request_id"].startswith("llm-")
    assert payload["prompt"] == "hello"
    assert "api_key" not in str(payload)

    executor.on_llm_response(
        {"request_id": payload["request_id"], "content": "hi", "usage": {"total_tokens": 1}}
    )
    result = await task
    assert result["content"] == "hi"
    assert result["usage"]["total_tokens"] == 1


@pytest.mark.asyncio
async def test_request_timeout(fake_ws):
    ex = ClientLLMExecutor(timeout_seconds=0.05)
    ex.bind(FakeStreamManager(FakeStream(fake_ws)))
    ex.set_llm_mode("u1", True)
    with pytest.raises(ClientLLMTimeout):
        await ex.request("u1", module="m", prompt="p", params=None)


@pytest.mark.asyncio
async def test_request_no_live_connection(executor):
    executor.bind(FakeStreamManager(None))
    executor.set_llm_mode("u1", True)
    with pytest.raises(ClientLLMUnavailable):
        await executor.request("u1", module="m", prompt="p", params=None)


@pytest.mark.asyncio
async def test_request_client_error(executor, fake_ws):
    executor.bind(FakeStreamManager(FakeStream(fake_ws)))
    executor.set_llm_mode("u1", True)
    task = asyncio.create_task(executor.request("u1", module="m", prompt="p", params=None))
    await asyncio.sleep(0)
    request_id = fake_ws.sent_events[0]["payload"]["request_id"]
    executor.on_llm_response({"request_id": request_id, "error": "401 invalid key"})
    with pytest.raises(ClientLLMError):
        await task


@pytest.mark.asyncio
async def test_clear_user_fails_pending(executor, fake_ws):
    executor.bind(FakeStreamManager(FakeStream(fake_ws)))
    executor.set_llm_mode("u1", True)
    task = asyncio.create_task(executor.request("u1", module="m", prompt="p", params=None))
    await asyncio.sleep(0)
    executor.clear_user("u1")
    with pytest.raises(ClientLLMUnavailable):
        await task
    assert not executor.is_enabled("u1")


def test_delegating_disabled_uses_inner():
    inner = FakeInner()
    wrapper = ClientDelegatingLLMInterface(inner, None)
    assert wrapper.default_parameters == {"temperature": 0.7}

    result = asyncio.run(wrapper.generate_response("p", params={"temperature": 0.5}))
    assert result["content"] == "server-answer"
    assert len(inner.calls) == 1


@pytest.mark.asyncio
async def test_delegating_enabled_uses_client(monkeypatch, executor, fake_ws):
    inner = FakeInner()
    executor.bind(FakeStreamManager(FakeStream(fake_ws)))
    executor.set_llm_mode("u1", True)
    wrapper = ClientDelegatingLLMInterface(inner, executor)
    monkeypatch.setattr(
        "src.utils.llm.client_delegating_interface.get_trace_context",
        lambda: {"user_id": "u1"},
    )

    task = asyncio.create_task(
        wrapper.generate_response(
            "p", params={"temperature": 0.5}, enable_thinking=True, use_json=True
        )
    )
    await asyncio.sleep(0)

    sent = fake_ws.sent_events[0]["payload"]
    assert sent["enable_thinking"] is True
    assert sent["use_json"] is True
    assert sent["provider"]["url"] == "https://example.com/v1/chat/completions"
    assert sent["provider"]["model"] == "test-model"
    assert "api_key" not in str(sent)

    executor.on_llm_response(
        {"request_id": sent["request_id"], "content": "client-answer", "usage": {"total_tokens": 2}}
    )
    result = await task
    assert result["content"] == "client-answer"
    assert inner.calls == []


@pytest.mark.asyncio
async def test_delegating_fallback_on_client_error(monkeypatch, executor, fake_ws):
    inner = FakeInner()
    executor.bind(FakeStreamManager(FakeStream(fake_ws)))
    executor.set_llm_mode("u1", True)
    wrapper = ClientDelegatingLLMInterface(inner, executor)
    monkeypatch.setattr(
        "src.utils.llm.client_delegating_interface.get_trace_context",
        lambda: {"user_id": "u1"},
    )

    task = asyncio.create_task(wrapper.generate_response("p"))
    await asyncio.sleep(0)
    request_id = fake_ws.sent_events[0]["payload"]["request_id"]
    executor.on_llm_response({"request_id": request_id, "error": "boom"})

    result = await task
    assert result["content"] == "server-answer"
    assert len(inner.calls) == 1


@pytest.mark.asyncio
async def test_vlm_delegating_enabled(monkeypatch, executor, fake_ws):
    inner = FakeVLMInner()
    executor.bind(FakeStreamManager(FakeStream(fake_ws)))
    executor.set_llm_mode("u1", True)
    wrapper = ClientDelegatingVLMInterface(inner, executor)
    monkeypatch.setattr(
        "src.utils.llm.client_delegating_interface.get_trace_context",
        lambda: {"user_id": "u1"},
    )

    task = asyncio.create_task(
        wrapper.generate_response("describe", image_base64="data:image/png;base64,AAA")
    )
    await asyncio.sleep(0)

    sent = fake_ws.sent_events[0]["payload"]
    assert sent["image_base64"].startswith("data:image/png")
    executor.on_llm_response({"request_id": sent["request_id"], "content": "vlm-client", "usage": None})

    result = await task
    assert result["content"] == "vlm-client"
    assert inner.calls == []


def test_llm_service_wraps_interfaces_when_executor_given(monkeypatch):
    monkeypatch.setattr(
        "src.utils.llm_service.LLMAPIFactory.create_interface",
        staticmethod(lambda config: FakeInner()),
    )
    monkeypatch.setattr(
        "src.utils.llm_service.VLMAPIFactory.create_interface",
        staticmethod(lambda config: FakeVLMInner()),
    )
    service = LLMService(
        {"available_llms": {"a": {}}, "available_vlms": {"v": {}}},
        client_llm_executor=ClientLLMExecutor(),
    )
    assert isinstance(service.llm_interfaces["a"], ClientDelegatingLLMInterface)
    assert isinstance(service.vlm_interfaces["v"], ClientDelegatingVLMInterface)


def test_llm_service_does_not_wrap_without_executor(monkeypatch):
    monkeypatch.setattr(
        "src.utils.llm_service.LLMAPIFactory.create_interface",
        staticmethod(lambda config: FakeInner()),
    )
    monkeypatch.setattr(
        "src.utils.llm_service.VLMAPIFactory.create_interface",
        staticmethod(lambda config: FakeVLMInner()),
    )
    service = LLMService({"available_llms": {"a": {}}, "available_vlms": {"v": {}}})
    assert isinstance(service.llm_interfaces["a"], FakeInner)
    assert isinstance(service.vlm_interfaces["v"], FakeVLMInner)
