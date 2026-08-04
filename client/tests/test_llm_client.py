"""桌面 client 的 LLM 客户端执行助手测试。"""

import json

import pytest

from src.network.ws_transport import WsTransport
from src.network.network_client import NetworkClient
from src.utils.llm_client import (
    CLIENT_JSON_UNSUPPORTED_MARKER,
    build_chat_completions_payload,
    call_llm_api,
    fetch_llm_json_required_modules,
    fetch_llm_providers,
    probe_llm_config,
    resolve_provider_base_url,
    resolve_provider_model,
    resolve_provider_vlm_model,
)

PRESETS = [
    {
        "name": "阿里云百炼（DashScope）",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": ["qwen3.5-plus", "qwen3.6-flash"],
        "vlm_models": ["qwen3-vl-plus"],
    },
    {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "models": ["deepseek-v4-flash", "deepseek-v4-pro"],
        "vlm_models": [],
    },
]


class FakeResponse:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self.text = "{}"
        self._data = data or {
            "choices": [{"message": {"content": "hi"}}],
            "usage": {"total_tokens": 5},
        }

    def json(self):
        return self._data


def test_build_payload_text():
    payload = build_chat_completions_payload(
        prompt="你是洛天依",
        model="test-model",
        params={"max_tokens": 1024, "temperature": 0.3},
        enable_thinking=True,
        use_json=True,
    )
    assert payload["model"] == "test-model"
    assert payload["messages"] == [{"role": "system", "content": "你是洛天依"}]
    assert payload["max_tokens"] == 1024
    assert payload["temperature"] == 0.3
    assert payload["enable_thinking"] is True
    assert payload["response_format"] == {"type": "json_object"}


def test_resolve_provider_base_url():
    assert (
        resolve_provider_base_url("DeepSeek", presets=PRESETS)
        == "https://api.deepseek.com/v1"
    )
    assert resolve_provider_base_url(None, presets=PRESETS) == ""
    assert resolve_provider_base_url("不存在的服务商", presets=PRESETS) == ""


def test_resolve_provider_model():
    assert resolve_provider_model("DeepSeek", presets=PRESETS) == "deepseek-v4-flash"
    assert resolve_provider_model(None, presets=PRESETS) == ""
    assert resolve_provider_model("不存在的服务商", presets=PRESETS) == ""


def test_resolve_provider_vlm_model():
    assert (
        resolve_provider_vlm_model("阿里云百炼（DashScope）", presets=PRESETS)
        == "qwen3-vl-plus"
    )
    assert resolve_provider_vlm_model("DeepSeek", presets=PRESETS) == ""
    assert resolve_provider_vlm_model(None, presets=PRESETS) == ""


def test_build_payload_image():
    payload = build_chat_completions_payload(
        prompt="描述这张图",
        model="test-vlm",
        params=None,
        image_base64="data:image/png;base64,AAA",
    )
    content = payload["messages"][0]["content"]
    assert content[0]["type"] == "text"
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"] == "data:image/png;base64,AAA"


def test_call_llm_api_success(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr("src.utils.llm_client.requests.post", fake_post)
    result = call_llm_api(
        url="https://example.com/v1/chat/completions",
        api_key="sk-user-key",
        payload={"model": "m", "messages": []},
    )
    assert result["content"] == "hi"
    assert result["usage"]["total_tokens"] == 5
    assert captured["headers"]["Authorization"] == "Bearer sk-user-key"
    assert captured["url"] == "https://example.com/v1/chat/completions"


def test_call_llm_api_http_error(monkeypatch):
    monkeypatch.setattr(
        "src.utils.llm_client.requests.post",
        lambda url, headers=None, json=None, timeout=None: FakeResponse(
            status_code=401,
            data={"error": "invalid api key"},
        ),
    )
    with pytest.raises(RuntimeError, match="401"):
        call_llm_api(url="https://example.com/v1", api_key="bad", payload={})


def test_call_llm_api_network_error(monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=None):
        raise ConnectionError("network down")

    monkeypatch.setattr("src.utils.llm_client.requests.post", fake_post)
    with pytest.raises(RuntimeError, match="network down"):
        call_llm_api(url="https://example.com/v1", api_key="sk", payload={})


def test_fetch_llm_providers_success(monkeypatch):
    captured = {}

    def fake_get(url, timeout=None):
        captured["url"] = url
        return FakeResponse(
            data={
                "providers": [
                    {
                        "name": "DeepSeek",
                        "base_url": "https://api.deepseek.com/v1",
                        "models": ["deepseek-v4-flash"],
                        "vlm_models": [],
                    }
                ]
            }
        )

    monkeypatch.setattr("src.utils.llm_client.requests.get", fake_get)
    providers = fetch_llm_providers("https://server.example.com")
    assert providers[0]["name"] == "DeepSeek"
    assert captured["url"] == "https://server.example.com/llm/providers"


def test_fetch_llm_providers_error(monkeypatch):
    monkeypatch.setattr(
        "src.utils.llm_client.requests.get",
        lambda url, timeout=None: FakeResponse(status_code=500),
    )
    with pytest.raises(RuntimeError, match="500"):
        fetch_llm_providers("https://server.example.com")


def test_fetch_llm_json_required_modules(monkeypatch):
    captured = {}

    def fake_get(url, timeout=None):
        captured["url"] = url
        return FakeResponse(
            data={
                "providers": [],
                "llm_json_required_modules": [
                    {"name": "topic_extractor", "label": "话题抽取"},
                    {"name": "memory_writer", "label": "记忆写入"},
                ],
                "vlm_json_required_modules": [],
            }
        )

    monkeypatch.setattr("src.utils.llm_client.requests.get", fake_get)
    llm_modules, vlm_modules = fetch_llm_json_required_modules(
        "https://server.example.com"
    )
    assert llm_modules == ["话题抽取", "记忆写入"]
    assert vlm_modules == []
    assert captured["url"] == "https://server.example.com/llm/providers"


def test_get_llm_providers_retries_after_failure(monkeypatch):
    calls = {"n": 0}

    def fake_fetch(base_url, timeout=15.0):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return [
            {
                "name": "DeepSeek",
                "base_url": "https://api.deepseek.com/v1",
                "model": "deepseek-v4-flash",
            }
        ]

    monkeypatch.setattr("src.network.network_client.fetch_llm_providers", fake_fetch)
    client = NetworkClient(base_url="https://server.example.com")

    assert client.get_llm_providers() == []
    # 失败不应被缓存：第二次调用会重新请求
    assert client.get_llm_providers()[0]["name"] == "DeepSeek"
    assert calls["n"] == 2


def test_submit_user_text_includes_llm_mode_when_key(monkeypatch):
    captured = {}

    def fake_submit(event_type, payload, ack_timeout, client_msg_id=None):
        captured["payload"] = payload
        return {"ok": True}

    transport = WsTransport(
        "wss://example.com",
        username_getter=lambda: "u",
        token_getter=lambda: "t",
        api_key_getter=lambda: "sk-user-key",
    )
    monkeypatch.setattr(transport, "_submit_user_event", fake_submit)
    transport.submit_user_text("hello")
    assert captured["payload"]["llm_mode"] == "client"


def test_submit_user_text_no_llm_mode_without_key(monkeypatch):
    captured = {}

    def fake_submit(event_type, payload, ack_timeout, client_msg_id=None):
        captured["payload"] = payload
        return {"ok": True}

    transport = WsTransport(
        "wss://example.com",
        username_getter=lambda: "u",
        token_getter=lambda: "t",
        api_key_getter=lambda: None,
    )
    monkeypatch.setattr(transport, "_submit_user_event", fake_submit)
    transport.submit_user_text("hello")
    assert "llm_mode" not in captured["payload"]


@pytest.mark.asyncio
async def test_handle_llm_request_uses_cached_config(monkeypatch):
    captured = {}

    async def fake_call(**kwargs):
        captured.update(kwargs)
        return {"content": "ok", "usage": None, "response_time_s": 0.1}

    monkeypatch.setattr("src.network.ws_transport.call_llm_api_async", fake_call)
    transport = WsTransport(
        "wss://example.com",
        username_getter=lambda: "u",
        token_getter=lambda: "t",
        api_key_getter=lambda: "sk-user",
        provider_getter=lambda: "DeepSeek",
        model_getter=lambda: "deepseek-v4-flash",
        base_url_getter=lambda: "https://api.deepseek.com/v1",
    )
    await transport._handle_llm_request(
        None,
        {
            "request_id": "req-1",
            "prompt": "hi",
            "provider": {"url": "https://server.example.com/v1", "model": "server-model"},
            "params": {"temperature": 0.5},
            "enable_thinking": False,
            "use_json": False,
        },
    )
    # 请求直接使用缓存的 base_url 与 model，而不是服务端下发的 url/model
    assert captured["url"] == "https://api.deepseek.com/v1/chat/completions"
    assert captured["api_key"] == "sk-user"
    assert captured["payload"]["model"] == "deepseek-v4-flash"


@pytest.mark.asyncio
async def test_handle_llm_request_uses_saved_model(monkeypatch):
    captured = {}

    async def fake_call(**kwargs):
        captured.update(kwargs)
        return {"content": "ok", "usage": None, "response_time_s": 0.1}

    monkeypatch.setattr("src.network.ws_transport.call_llm_api_async", fake_call)
    transport = WsTransport(
        "wss://example.com",
        username_getter=lambda: "u",
        token_getter=lambda: "t",
        api_key_getter=lambda: "sk-user",
        provider_getter=lambda: "DeepSeek",
        model_getter=lambda: "deepseek-v4-pro",
        base_url_getter=lambda: "https://api.deepseek.com/v1",
    )
    await transport._handle_llm_request(
        None,
        {
            "request_id": "req-2",
            "prompt": "hi",
            "provider": {"model": "server-model"},
            "params": {},
        },
    )
    assert captured["payload"]["model"] == "deepseek-v4-pro"


@pytest.mark.asyncio
async def test_handle_llm_request_uses_cached_base_url_and_model(monkeypatch):
    """请求直接使用缓存的 base_url 与模型名，不依赖预设解析。"""
    captured = {}

    async def fake_call(**kwargs):
        captured.update(kwargs)
        return {"content": "ok", "usage": None, "response_time_s": 0.1}

    monkeypatch.setattr("src.network.ws_transport.call_llm_api_async", fake_call)
    transport = WsTransport(
        "wss://example.com",
        username_getter=lambda: "u",
        token_getter=lambda: "t",
        api_key_getter=lambda: "sk-user",
        provider_getter=lambda: "不存在的服务商",
        model_getter=lambda: "cached-model",
        base_url_getter=lambda: "https://cached.example.com/v1",
    )
    await transport._handle_llm_request(
        None,
        {
            "request_id": "req-3",
            "prompt": "hi",
            "provider": {"model": "server-model"},
            "params": {},
        },
    )
    assert captured["url"] == "https://cached.example.com/v1/chat/completions"
    assert captured["payload"]["model"] == "cached-model"


@pytest.mark.asyncio
async def test_handle_llm_request_uses_vlm_model_for_image(monkeypatch):
    """图片请求使用缓存的图片理解模型。"""
    captured = {}

    async def fake_call(**kwargs):
        captured.update(kwargs)
        return {"content": "ok", "usage": None, "response_time_s": 0.1}

    monkeypatch.setattr("src.network.ws_transport.call_llm_api_async", fake_call)
    transport = WsTransport(
        "wss://example.com",
        username_getter=lambda: "u",
        token_getter=lambda: "t",
        api_key_getter=lambda: "sk-user",
        provider_getter=lambda: "阿里云百炼（DashScope）",
        model_getter=lambda: "qwen3.5-plus",
        vlm_provider_getter=lambda: "阿里云百炼（DashScope）",
        vlm_model_getter=lambda: "qwen3-vl-plus",
        vlm_api_key_getter=lambda: "sk-vlm",
        base_url_getter=lambda: "https://dashscope.aliyuncs.com/compatible-mode/v1",
        vlm_base_url_getter=lambda: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    await transport._handle_llm_request(
        None,
        {
            "request_id": "req-img",
            "prompt": "描述图片",
            "image_base64": "data:image/png;base64,AAA",
            "provider": {},
            "params": {},
        },
    )
    assert captured["payload"]["model"] == "qwen3-vl-plus"
    assert captured["api_key"] == "sk-vlm"


@pytest.mark.asyncio
async def test_handle_llm_request_merges_cached_params(monkeypatch):
    """用户自定义参数覆盖服务端下发参数。"""
    captured = {}

    async def fake_call(**kwargs):
        captured.update(kwargs)
        return {"content": "ok", "usage": None, "response_time_s": 0.1}

    monkeypatch.setattr("src.network.ws_transport.call_llm_api_async", fake_call)
    transport = WsTransport(
        "wss://example.com",
        username_getter=lambda: "u",
        token_getter=lambda: "t",
        api_key_getter=lambda: "sk-user",
        model_getter=lambda: "m",
        base_url_getter=lambda: "https://example.com/v1",
        params_getter=lambda: {"temperature": 0.2, "max_tokens": 2048},
    )
    await transport._handle_llm_request(
        None,
        {
            "request_id": "req-params",
            "prompt": "hi",
            "provider": {},
            "params": {"temperature": 0.9, "top_p": 0.5},
        },
    )
    body = captured["payload"]
    assert body["temperature"] == 0.2  # 用户参数覆盖
    assert body["max_tokens"] == 2048  # 仅用户设置
    assert body["top_p"] == 0.5  # 服务端参数保留


@pytest.mark.asyncio
async def test_handle_llm_request_follows_server_suggestions_when_capable(monkeypatch):
    """模型支持且服务端建议时，才带上思考/JSON 开关。"""
    captured = {}

    async def fake_call(**kwargs):
        captured.update(kwargs)
        return {"content": "ok", "usage": None, "response_time_s": 0.1}

    monkeypatch.setattr("src.network.ws_transport.call_llm_api_async", fake_call)
    transport = WsTransport(
        "wss://example.com",
        username_getter=lambda: "u",
        token_getter=lambda: "t",
        api_key_getter=lambda: "sk-user",
        model_getter=lambda: "m",
        base_url_getter=lambda: "https://example.com/v1",
        flags_getter=lambda: {"enable_thinking": True, "use_json": True},
    )
    await transport._handle_llm_request(
        None,
        {
            "request_id": "req-flags",
            "prompt": "hi",
            "provider": {},
            "params": {},
            "enable_thinking": True,
            "use_json": True,
        },
    )
    body = captured["payload"]
    assert body["enable_thinking"] is True
    assert body["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_handle_llm_request_skips_switch_when_server_does_not_suggest(monkeypatch):
    """模型支持思考，但服务端本次不推荐时不应携带。"""
    captured = {}

    async def fake_call(**kwargs):
        captured.update(kwargs)
        return {"content": "ok", "usage": None, "response_time_s": 0.1}

    monkeypatch.setattr("src.network.ws_transport.call_llm_api_async", fake_call)
    transport = WsTransport(
        "wss://example.com",
        username_getter=lambda: "u",
        token_getter=lambda: "t",
        api_key_getter=lambda: "sk-user",
        model_getter=lambda: "m",
        base_url_getter=lambda: "https://example.com/v1",
        flags_getter=lambda: {"enable_thinking": True, "use_json": True},
    )
    await transport._handle_llm_request(
        None,
        {
            "request_id": "req-flags-off",
            "prompt": "hi",
            "provider": {},
            "params": {},
            "enable_thinking": False,
            "use_json": False,
        },
    )
    body = captured["payload"]
    assert "enable_thinking" not in body
    assert "response_format" not in body


@pytest.mark.asyncio
async def test_handle_llm_request_json_needed_but_not_capable_errors(monkeypatch):
    """服务端需要 JSON 但模型未勾选支持时，不调用服务商并回传标记错误。"""
    captured = {}

    async def fake_call(**kwargs):
        captured["called"] = True
        return {"content": "ok", "usage": None, "response_time_s": 0.1}

    monkeypatch.setattr("src.network.ws_transport.call_llm_api_async", fake_call)
    transport = WsTransport(
        "wss://example.com",
        username_getter=lambda: "u",
        token_getter=lambda: "t",
        api_key_getter=lambda: "sk-user",
        model_getter=lambda: "m",
        base_url_getter=lambda: "https://example.com/v1",
        flags_getter=lambda: {"enable_thinking": False, "use_json": False},
    )
    fake_ws = FakeClientWs()
    transport._ws = fake_ws
    await transport._handle_llm_request(
        None,
        {
            "request_id": "req-json-miss",
            "prompt": "hi",
            "provider": {},
            "params": {},
            "enable_thinking": False,
            "use_json": True,
        },
    )
    assert "called" not in captured
    assert fake_ws.sent
    payload = json.loads(fake_ws.sent[0])["payload"]
    assert payload["error"] == CLIENT_JSON_UNSUPPORTED_MARKER


@pytest.mark.asyncio
async def test_handle_llm_request_uses_vlm_flags_for_image(monkeypatch):
    """图片请求按图片理解模型的能力与服务端建议应用开关。"""
    captured = {}

    async def fake_call(**kwargs):
        captured.update(kwargs)
        return {"content": "ok", "usage": None, "response_time_s": 0.1}

    monkeypatch.setattr("src.network.ws_transport.call_llm_api_async", fake_call)
    transport = WsTransport(
        "wss://example.com",
        username_getter=lambda: "u",
        token_getter=lambda: "t",
        api_key_getter=lambda: "sk-user",
        model_getter=lambda: "m",
        vlm_model_getter=lambda: "vlm-m",
        vlm_api_key_getter=lambda: "sk-vlm",
        base_url_getter=lambda: "https://example.com/v1",
        vlm_base_url_getter=lambda: "https://example.com/v1",
        flags_getter=lambda: {"enable_thinking": False, "use_json": False},
        vlm_flags_getter=lambda: {"enable_thinking": True, "use_json": True},
    )
    await transport._handle_llm_request(
        None,
        {
            "request_id": "req-vlm-flags",
            "prompt": "describe",
            "image_base64": "data:image/png;base64,AAA",
            "provider": {},
            "params": {},
            "enable_thinking": True,
            "use_json": True,
        },
    )
    body = captured["payload"]
    assert body["enable_thinking"] is True
    assert body["response_format"] == {"type": "json_object"}


class FakeClientWs:
    def __init__(self):
        self.sent = []

    async def send(self, raw):
        self.sent.append(raw)


@pytest.mark.asyncio
async def test_handle_llm_request_missing_cached_base_url_errors():
    transport = WsTransport(
        "wss://example.com",
        username_getter=lambda: "u",
        token_getter=lambda: "t",
        api_key_getter=lambda: "sk-user",
        provider_getter=lambda: "DeepSeek",
        model_getter=lambda: "deepseek-v4-flash",
        base_url_getter=lambda: None,
    )
    fake_ws = FakeClientWs()
    transport._ws = fake_ws
    await transport._handle_llm_request(
        None,
        {"request_id": "req-4", "prompt": "hi", "provider": {}, "params": {}},
    )
    assert fake_ws.sent
    payload = json.loads(fake_ws.sent[0])["payload"]
    assert "error" in payload


def test_probe_llm_config_builds_probe_payload(monkeypatch):
    """保存前探测：开关与最小参数正确构造请求体。"""
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("src.utils.llm_client.requests.post", fake_post)
    probe_llm_config(
        base_url="https://example.com/v1",
        api_key="sk-user",
        model="test-model",
        flags={"enable_thinking": True, "use_json": True},
        params={"temperature": 0.9, "max_tokens": 2048},
        timeout=15.0,
    )
    assert captured["url"] == "https://example.com/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer sk-user"
    body = captured["json"]
    assert body["model"] == "test-model"
    assert body["max_tokens"] == 8
    assert body["temperature"] == 0
    assert body["enable_thinking"] is True
    assert body["response_format"] == {"type": "json_object"}
    assert "ok" in body["messages"][0]["content"]
    assert captured["timeout"] == 15.0


def test_probe_llm_config_plain_ping(monkeypatch):
    """未开启任何开关时，探测体不带对应字段。"""
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr("src.utils.llm_client.requests.post", fake_post)
    probe_llm_config(
        base_url="https://example.com/v1",
        api_key="sk-user",
        model="m",
        flags={"enable_thinking": False, "use_json": False},
    )
    body = captured["json"]
    assert body["messages"][0]["content"] == "ping"
    assert "enable_thinking" not in body
    assert "response_format" not in body


def test_probe_llm_config_raises_on_provider_error(monkeypatch):
    """保存前探测失败（如开关不被支持）应中止并抛出具体错误。"""
    monkeypatch.setattr(
        "src.utils.llm_client.requests.post",
        lambda url, headers=None, json=None, timeout=None: FakeResponse(
            status_code=400,
            data={"error": {"message": "unsupported switch", "code": "InvalidParameter"}},
        ),
    )
    with pytest.raises(RuntimeError, match="400"):
        probe_llm_config(
            base_url="https://example.com/v1",
            api_key="sk",
            model="m",
            flags={"use_json": True},
        )
