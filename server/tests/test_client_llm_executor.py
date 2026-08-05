"""ClientLLMExecutor 与 ClientDelegatingLLM/VLMInterface 的单元测试。"""

import asyncio
import inspect
from types import SimpleNamespace

import pytest

from src.utils.llm.client_delegating_interface import (
    CLIENT_JSON_UNSUPPORTED_MARKER,
    ClientDelegatingLLMInterface,
    ClientDelegatingVLMInterface,
)
from src.utils.llm.client_llm_executor import (
    ClientLLMError,
    ClientLLMExecutor,
    ClientLLMTimeout,
    ClientLLMUnavailable,
    _looks_like_key_error,
    _looks_like_network_error,
)
from src.chat_session.chat_stream_manager import ChatStreamManager
from src.utils.llm.llm_api_interface import LLMAPIInterface
from src.utils.llm_service import LLMService
from src.utils.vision.vlm_api_interface import VLMAPIInterface


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

    def lost_connection(self):
        self.ws_connection = None

    def reconnect(self, websocket, client_mode=None):
        """模拟 ChatStream.reconnect：用新连接替换当前连接。"""
        self.ws_connection = self._as_connection(websocket, client_mode)

    @staticmethod
    def _as_connection(websocket, client_mode=None):
        """已是连接对象（含 websocket 属性）则直接复用，保证身份比较；否则包装。"""
        if hasattr(websocket, "websocket"):
            websocket.client_mode = dict(
                client_mode or getattr(websocket, "client_mode", None)
                or {"text": False, "vlm": False}
            )
            return websocket
        return SimpleNamespace(
            websocket=websocket,
            client_mode=dict(client_mode or {"text": False, "vlm": False}),
        )


class FakeStreamManager:
    def __init__(self, stream=None):
        self.stream = stream

    def get_stream_by_user_uuid(self, user_id):
        return self.stream


class FakeExecutor:
    """模拟 ClientLLMExecutor，用于测试包装接口的重试/通知逻辑。"""

    def __init__(self, enabled=True):
        self.enabled = enabled
        self.request_calls = 0
        self.notices = []
        self.behavior = []

    def is_enabled(self, user_id, vlm=False):
        return self.enabled

    async def request(self, user_id, **kwargs):
        self.request_calls += 1
        if self.behavior:
            item = self.behavior.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        return {"content": "client-answer", "usage": None, "response_time_s": 0.1}

    async def notify_user(self, user_id, message):
        self.notices.append(message)


def test_on_llm_response_is_sync():
    """on_llm_response 是同步回调，server_main 中不能用 await 调用。"""
    assert not inspect.iscoroutinefunction(ClientLLMExecutor.on_llm_response)


def test_error_classification():
    assert _looks_like_key_error("LLM provider returned HTTP 401: invalid api key") is True
    assert _looks_like_key_error("HTTP 403 Access denied") is True
    assert _looks_like_key_error("connection refused") is False
    assert _looks_like_network_error("LLM provider request failed: Connection error") is True
    assert _looks_like_network_error("timed out") is True
    assert _looks_like_network_error("HTTP 401 invalid api key") is False


def test_is_enabled_uses_connection_flag(executor, fake_ws):
    executor.bind(FakeStreamManager(FakeStream(fake_ws, client_mode={"text": True})))
    assert executor.is_enabled("u1") is True
    executor.bind(FakeStreamManager(FakeStream(fake_ws, client_mode={"text": False})))
    assert executor.is_enabled("u1") is False
    executor.bind(FakeStreamManager(None))
    assert executor.is_enabled("u1") is False


def test_multi_connection_mode_follows_active_connection(executor):
    """多设备场景：llm_mode 只跟随当前活跃连接，不随用户残留。"""
    device_a_ws = FakeWebSocket()
    device_b_ws = FakeWebSocket()
    stream = FakeStream(device_a_ws, client_mode={"text": True})
    executor.bind(FakeStreamManager(stream))

    # 设备 A 声明了客户端执行
    assert executor.is_enabled("u1") is True

    # 设备 B 接管连接（模拟 reconnect），未声明客户端执行
    stream.reconnect(device_b_ws, client_mode={"text": False})
    assert executor.is_enabled("u1") is False

    # 设备 B 声明客户端执行后恢复
    stream.reconnect(device_b_ws, client_mode={"text": True})
    assert executor.is_enabled("u1") is True


@pytest.mark.asyncio
async def test_multi_connection_request_only_goes_to_enabled_active_connection(executor):
    """多设备场景：请求只发给声明了客户端执行的活跃连接。"""
    device_a_ws = FakeWebSocket()
    device_b_ws = FakeWebSocket()
    stream = FakeStream(device_a_ws, client_mode={"text": True})
    executor.bind(FakeStreamManager(stream))

    # 设备 B 接管但未声明客户端执行：不应转发请求，也不应发到 B
    stream.reconnect(device_b_ws, client_mode={"text": False})
    with pytest.raises(ClientLLMUnavailable):
        await executor.request("u1", module="m", prompt="p", params=None)
    assert device_b_ws.sent_events == []

    # 设备 B 声明客户端执行后：请求应发到 B 并能正常完成
    stream.reconnect(device_b_ws, client_mode={"text": True})
    task = asyncio.create_task(
        executor.request("u1", module="m", prompt="p", params=None)
    )
    await asyncio.sleep(0)
    assert device_b_ws.sent_events
    request_id = device_b_ws.sent_events[0]["payload"]["request_id"]
    executor.on_llm_response(
        {"request_id": request_id, "content": "ok", "usage": None}
    )
    result = await task
    assert result["content"] == "ok"
    assert device_a_ws.sent_events == []


@pytest.mark.asyncio
async def test_multi_connection_device_a_reconnects_back(executor):
    """设备 A 重新连接回来后：初始未声明，声明后恢复客户端执行。"""
    device_a_ws = FakeWebSocket()
    device_b_ws = FakeWebSocket()
    stream = FakeStream(device_a_ws, client_mode={"text": True})
    executor.bind(FakeStreamManager(stream))
    assert executor.is_enabled("u1") is True

    # 设备 B 接管连接，未声明客户端执行
    stream.reconnect(device_b_ws, client_mode={"text": False})
    assert executor.is_enabled("u1") is False

    # 设备 A 重新连接回来：新连接初始未声明
    device_a_new_ws = FakeWebSocket()
    stream.reconnect(device_a_new_ws, client_mode={"text": False})
    assert executor.is_enabled("u1") is False
    assert device_a_new_ws.sent_events == []

    # A 发消息携带 llm_mode=client（server_main 写入连接标记）
    stream.ws_connection.client_mode = {"text": True}
    assert executor.is_enabled("u1") is True

    task = asyncio.create_task(
        executor.request("u1", module="m", prompt="p", params=None)
    )
    await asyncio.sleep(0)
    assert device_a_new_ws.sent_events
    request_id = device_a_new_ws.sent_events[0]["payload"]["request_id"]
    executor.on_llm_response(
        {"request_id": request_id, "content": "ok", "usage": None}
    )
    result = await task
    assert result["content"] == "ok"
    assert device_b_ws.sent_events == []


def test_ws_lost_connection_ignores_stale_connection():
    """旧连接断开不应清掉新连接的活跃状态（走真实 ws_lost_connection 入口）。"""
    manager = ChatStreamManager({}, None, None, None, None)
    device_a = SimpleNamespace(websocket=FakeWebSocket(), user_uuid="u1")
    stream = FakeStream(device_a, client_mode={"text": True})
    manager.user_streams[("u1", "luotianyi")] = stream

    # 设备 B 接管（reconnect 替换当前连接）
    device_b = SimpleNamespace(websocket=FakeWebSocket(), user_uuid="u1")
    stream.reconnect(device_b, client_mode={"text": False})

    # 旧连接 A 断开：不清理当前活跃的 B
    assert manager.ws_lost_connection(device_a) is False
    assert stream.ws_connection is device_b

    # 当前活跃连接 B 断开：清理
    assert manager.ws_lost_connection(device_b) is True
    assert stream.ws_connection is None


def test_ws_lost_connection_per_user_isolation():
    """ws_lost_connection 只清理断开者所属用户的活跃流。"""
    manager = ChatStreamManager({}, None, None, None, None)
    user_a_conn = SimpleNamespace(websocket=FakeWebSocket(), user_uuid="u1")
    user_b_conn = SimpleNamespace(websocket=FakeWebSocket(), user_uuid="u2")
    stream_a = FakeStream(user_a_conn)
    stream_b = FakeStream(user_b_conn)
    manager.user_streams[("u1", "luotianyi")] = stream_a
    manager.user_streams[("u2", "luotianyi")] = stream_b

    manager.ws_lost_connection(user_a_conn)
    assert stream_a.ws_connection is None
    assert stream_b.ws_connection is user_b_conn


@pytest.mark.asyncio
async def test_clear_user_ignores_stale_connection(executor, fake_ws):
    """旧连接断开时，不失败当前连接发起的 pending 请求。"""
    stream = FakeStream(fake_ws, client_mode={"text": True})
    executor.bind(FakeStreamManager(stream))
    task = asyncio.create_task(
        executor.request("u1", module="m", prompt="p", params=None)
    )
    await asyncio.sleep(0)

    # 旧连接断开：pending 保留
    stale_connection = SimpleNamespace(websocket=object(), user_uuid="u1")
    executor.clear_user("u1", stale_connection)
    assert not task.done()

    # 当前连接断开：pending 被失败
    executor.clear_user("u1", stream.ws_connection)
    with pytest.raises(ClientLLMUnavailable):
        await task


@pytest.mark.asyncio
async def test_notify_goes_to_request_connection_after_switch(executor):
    """设备切换后，失败通知仍发回实际处理请求的连接，而不是新的活跃连接。"""
    device_a_ws = FakeWebSocket()
    device_b_ws = FakeWebSocket()
    stream = FakeStream(device_a_ws, client_mode={"text": True})
    executor.bind(FakeStreamManager(stream))

    # 请求发到设备 A
    task = asyncio.create_task(
        executor.request("u1", module="m", prompt="p", params=None)
    )
    await asyncio.sleep(0)
    request_id = device_a_ws.sent_events[-1]["payload"]["request_id"]

    # 请求进行中，设备 B 接管活跃连接
    stream.reconnect(device_b_ws, client_mode={"text": False})

    # A 返回 key 错误
    executor.on_llm_response(
        {"request_id": request_id, "error": "HTTP 401 invalid api key"}
    )
    with pytest.raises(ClientLLMError):
        await task

    # 通知应发回 A，而不是新的活跃连接 B
    await executor.notify_user("u1", "测试通知")
    error_events_a = [e for e in device_a_ws.sent_events if e["type"] == "error"]
    error_events_b = [e for e in device_b_ws.sent_events if e["type"] == "error"]
    assert len(error_events_a) == 1
    assert error_events_b == []


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
    executor.bind(FakeStreamManager(FakeStream(fake_ws, client_mode={"text": True})))

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
    ex.bind(FakeStreamManager(FakeStream(fake_ws, client_mode={"text": True})))
    with pytest.raises(ClientLLMTimeout):
        await ex.request("u1", module="m", prompt="p", params=None)


@pytest.mark.asyncio
async def test_request_no_live_connection(executor):
    executor.bind(FakeStreamManager(None))
    with pytest.raises(ClientLLMUnavailable):
        await executor.request("u1", module="m", prompt="p", params=None)


@pytest.mark.asyncio
async def test_request_client_error(executor, fake_ws):
    executor.bind(FakeStreamManager(FakeStream(fake_ws, client_mode={"text": True})))
    task = asyncio.create_task(executor.request("u1", module="m", prompt="p", params=None))
    await asyncio.sleep(0)
    request_id = fake_ws.sent_events[0]["payload"]["request_id"]
    executor.on_llm_response({"request_id": request_id, "error": "401 invalid key"})
    with pytest.raises(ClientLLMError):
        await task


@pytest.mark.asyncio
async def test_request_classifies_errors(executor, fake_ws):
    executor.bind(FakeStreamManager(FakeStream(fake_ws, client_mode={"text": True})))

    # key 类错误
    task = asyncio.create_task(
        executor.request("u1", module="m", prompt="p", params=None)
    )
    await asyncio.sleep(0)
    request_id = fake_ws.sent_events[-1]["payload"]["request_id"]
    executor.on_llm_response(
        {"request_id": request_id, "error": "LLM provider returned HTTP 401: invalid api key"}
    )
    with pytest.raises(ClientLLMError):
        await task

    # 网络类错误
    task = asyncio.create_task(
        executor.request("u1", module="m", prompt="p", params=None)
    )
    await asyncio.sleep(0)
    request_id = fake_ws.sent_events[-1]["payload"]["request_id"]
    executor.on_llm_response(
        {"request_id": request_id, "error": "LLM provider request failed: Connection error"}
    )
    with pytest.raises(ClientLLMError):
        await task

    # 其他错误保持 ClientLLMError
    task = asyncio.create_task(
        executor.request("u1", module="m", prompt="p", params=None)
    )
    await asyncio.sleep(0)
    request_id = fake_ws.sent_events[-1]["payload"]["request_id"]
    executor.on_llm_response({"request_id": request_id, "error": "HTTP 400 bad request"})
    with pytest.raises(ClientLLMError):
        await task


@pytest.mark.asyncio
async def test_notify_user_sends_error_event(executor, fake_ws):
    executor.bind(FakeStreamManager(FakeStream(fake_ws, client_mode={"text": True})))
    task = asyncio.create_task(
        executor.request("u1", module="m", prompt="p", params=None)
    )
    await asyncio.sleep(0)
    request_id = fake_ws.sent_events[0]["payload"]["request_id"]

    await executor.notify_user("u1", "测试通知")
    error_events = [e for e in fake_ws.sent_events if e["type"] == "error"]
    assert error_events
    event = error_events[0]
    assert event["type"] == "error"
    assert event["payload"]["code"] == "LLM_CLIENT_ERROR"
    assert event["payload"]["message"] == "测试通知"

    executor.on_llm_response(
        {"request_id": request_id, "content": "ok", "usage": None}
    )
    result = await task
    assert result["content"] == "ok"


@pytest.mark.asyncio
async def test_notify_user_unknown_is_noop(executor, fake_ws):
    executor.bind(FakeStreamManager(FakeStream(fake_ws, client_mode={"text": True})))
    await executor.notify_user("u1", "不应发送")
    assert fake_ws.sent_events == []


@pytest.mark.asyncio
async def test_clear_user_fails_pending(executor, fake_ws):
    executor.bind(FakeStreamManager(FakeStream(fake_ws, client_mode={"text": True})))
    task = asyncio.create_task(executor.request("u1", module="m", prompt="p", params=None))
    await asyncio.sleep(0)
    executor.clear_user("u1")
    with pytest.raises(ClientLLMUnavailable):
        await task


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
    executor.bind(FakeStreamManager(FakeStream(fake_ws, client_mode={"text": True})))
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
async def test_delegating_json_unsupported_falls_back_to_server(monkeypatch, executor, fake_ws):
    inner = FakeInner()
    executor.bind(FakeStreamManager(FakeStream(fake_ws, client_mode={"text": True})))
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
    request_id = fake_ws.sent_events[0]["payload"]["request_id"]
    executor.on_llm_response(
        {"request_id": request_id, "error": CLIENT_JSON_UNSUPPORTED_MARKER}
    )

    result = await task
    assert result["content"] == "server-answer"
    assert len(inner.calls) == 1
    # 能力不足导致的回退不应向用户发错误通知
    error_events = [e for e in fake_ws.sent_events if e["type"] == "error"]
    assert error_events == []


@pytest.mark.asyncio
async def test_delegating_client_error_raises_and_notifies(monkeypatch, executor, fake_ws):
    inner = FakeInner()
    executor.bind(FakeStreamManager(FakeStream(fake_ws, client_mode={"text": True})))
    wrapper = ClientDelegatingLLMInterface(inner, executor)
    monkeypatch.setattr(
        "src.utils.llm.client_delegating_interface.get_trace_context",
        lambda: {"user_id": "u1"},
    )

    task = asyncio.create_task(wrapper.generate_response("p"))
    await asyncio.sleep(0)
    request_id = fake_ws.sent_events[0]["payload"]["request_id"]
    executor.on_llm_response({"request_id": request_id, "error": "boom"})

    with pytest.raises(ClientLLMError):
        await task
    assert len(inner.calls) == 0
    error_events = [e for e in fake_ws.sent_events if e["type"] == "error"]
    assert error_events
    assert error_events[0]["payload"]["code"] == "LLM_CLIENT_ERROR"


@pytest.mark.asyncio
async def test_vlm_delegating_enabled(monkeypatch, executor, fake_ws):
    inner = FakeVLMInner()
    executor.bind(FakeStreamManager(FakeStream(fake_ws, client_mode={"vlm": True})))
    wrapper = ClientDelegatingVLMInterface(inner, executor)
    monkeypatch.setattr(
        "src.utils.llm.client_delegating_interface.get_trace_context",
        lambda: {"user_id": "u1"},
    )

    task = asyncio.create_task(
        wrapper.generate_response(
            "describe",
            image_base64="data:image/png;base64,AAA",
            extra_body={"enable_thinking": True},
            response_format={"type": "json_object"},
        )
    )
    await asyncio.sleep(0)

    sent = fake_ws.sent_events[0]["payload"]
    assert sent["image_base64"].startswith("data:image/png")
    assert sent["enable_thinking"] is True
    assert sent["use_json"] is True
    executor.on_llm_response({"request_id": sent["request_id"], "content": "vlm-client", "usage": None})

    result = await task
    assert result["content"] == "vlm-client"
    assert inner.calls == []


@pytest.mark.asyncio
async def test_vlm_not_delegated_when_only_llm_enabled(monkeypatch, executor, fake_ws):
    """LLM 启用而 VLM 未启用时，VLM 走服务端 key，不发送 llm_request。"""
    inner = FakeVLMInner()
    executor.bind(FakeStreamManager(FakeStream(fake_ws, client_mode={"text": True})))
    wrapper = ClientDelegatingVLMInterface(inner, executor)
    monkeypatch.setattr(
        "src.utils.llm.client_delegating_interface.get_trace_context",
        lambda: {"user_id": "u1"},
    )

    result = await wrapper.generate_response(
        "describe", image_base64="data:image/png;base64,AAA"
    )
    assert result["content"] == "vlm-answer"
    assert len(inner.calls) == 1
    assert fake_ws.sent_events == []


@pytest.mark.asyncio
async def test_vlm_delegating_json_unsupported_falls_back_to_server(monkeypatch, executor, fake_ws):
    inner = FakeVLMInner()
    executor.bind(FakeStreamManager(FakeStream(fake_ws, client_mode={"vlm": True})))
    wrapper = ClientDelegatingVLMInterface(inner, executor)
    monkeypatch.setattr(
        "src.utils.llm.client_delegating_interface.get_trace_context",
        lambda: {"user_id": "u1"},
    )

    task = asyncio.create_task(
        wrapper.generate_response(
            "describe",
            image_base64="data:image/png;base64,AAA",
            response_format={"type": "json_object"},
        )
    )
    await asyncio.sleep(0)
    request_id = fake_ws.sent_events[0]["payload"]["request_id"]
    executor.on_llm_response(
        {"request_id": request_id, "error": CLIENT_JSON_UNSUPPORTED_MARKER}
    )

    result = await task
    assert result["content"] == "vlm-answer"
    assert len(inner.calls) == 1
    error_events = [e for e in fake_ws.sent_events if e["type"] == "error"]
    assert error_events == []


@pytest.mark.asyncio
async def test_wrapper_retries_network_errors_then_succeeds(monkeypatch):
    inner = FakeInner()
    executor = FakeExecutor()
    executor.behavior = [
        ClientLLMError("connection refused"),
        ClientLLMError("connection refused"),
        {"content": "ok-after-retry", "usage": None, "response_time_s": 0.1},
    ]
    wrapper = ClientDelegatingLLMInterface(inner, executor)
    monkeypatch.setattr(
        "src.utils.llm.client_delegating_interface.get_trace_context",
        lambda: {"user_id": "u1"},
    )
    monkeypatch.setattr(
        "src.utils.llm.client_delegating_interface.CLIENT_RETRY_INITIAL_DELAY", 0
    )

    result = await wrapper.generate_response("p")
    assert result["content"] == "ok-after-retry"
    assert executor.request_calls == 3
    assert executor.notices == []
    assert inner.calls == []


@pytest.mark.asyncio
async def test_wrapper_network_failure_notifies_and_raises(monkeypatch):
    inner = FakeInner()
    executor = FakeExecutor()
    executor.behavior = [
        ClientLLMError("connection refused"),
        ClientLLMError("connection refused"),
        ClientLLMError("connection refused"),
    ]
    wrapper = ClientDelegatingLLMInterface(inner, executor)
    monkeypatch.setattr(
        "src.utils.llm.client_delegating_interface.get_trace_context",
        lambda: {"user_id": "u1"},
    )
    monkeypatch.setattr(
        "src.utils.llm.client_delegating_interface.CLIENT_RETRY_INITIAL_DELAY", 0
    )

    with pytest.raises(ClientLLMError):
        await wrapper.generate_response("p")
    assert executor.request_calls == 3
    assert len(executor.notices) == 1
    assert len(inner.calls) == 0


@pytest.mark.asyncio
async def test_wrapper_key_error_no_retry_notifies_and_raises(monkeypatch):
    inner = FakeInner()
    executor = FakeExecutor()
    executor.behavior = [ClientLLMError("HTTP 401 invalid api key")]
    wrapper = ClientDelegatingLLMInterface(inner, executor)
    monkeypatch.setattr(
        "src.utils.llm.client_delegating_interface.get_trace_context",
        lambda: {"user_id": "u1"},
    )

    with pytest.raises(ClientLLMError):
        await wrapper.generate_response("p")
    assert executor.request_calls == 1  # key 错误不重试
    assert len(executor.notices) == 1
    assert "API Key" in executor.notices[0]
    assert len(inner.calls) == 0


@pytest.mark.asyncio
async def test_vlm_wrapper_key_error_notifies_and_raises(monkeypatch):
    inner = FakeVLMInner()
    executor = FakeExecutor()
    executor.behavior = [ClientLLMError("HTTP 403 forbidden")]
    wrapper = ClientDelegatingVLMInterface(inner, executor)
    monkeypatch.setattr(
        "src.utils.llm.client_delegating_interface.get_trace_context",
        lambda: {"user_id": "u1"},
    )

    with pytest.raises(ClientLLMError):
        await wrapper.generate_response(
            "describe", image_base64="data:image/png;base64,AAA"
        )
    assert executor.request_calls == 1
    assert len(executor.notices) == 1
    assert len(inner.calls) == 0


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
