"""桌面 client 的 LLM 客户端执行助手测试。"""

import pytest

from src.network.ws_transport import WsTransport
from src.network.network_client import NetworkClient
from src.utils.llm_client import (
    build_chat_completions_payload,
    call_llm_api,
    fetch_llm_providers,
    fetch_provider_models,
    resolve_provider_base_url,
    resolve_provider_model,
)

PRESETS = [
    {
        "name": "阿里云百炼（DashScope）",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen3.5-plus",
    },
    {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-flash",
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
    assert (
        resolve_provider_base_url(None, presets=PRESETS)
        == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    assert (
        resolve_provider_base_url("不存在的服务商", presets=PRESETS)
        == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )


def test_resolve_provider_model():
    assert resolve_provider_model("DeepSeek", presets=PRESETS) == "deepseek-v4-flash"
    assert resolve_provider_model(None, presets=PRESETS) == "qwen3.5-plus"
    assert resolve_provider_model("不存在的服务商", presets=PRESETS) == "qwen3.5-plus"


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


def test_fetch_provider_models_success(monkeypatch):
    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        return FakeResponse(
            data={"object": "list", "data": [{"id": "qwen3.5-plus"}, {"id": "deepseek-chat"}]}
        )

    monkeypatch.setattr("src.utils.llm_client.requests.get", fake_get)
    models = fetch_provider_models(
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "sk-test",
    )
    assert models == ["qwen3.5-plus", "deepseek-chat"]
    assert captured["url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1/models"
    assert captured["headers"]["Authorization"] == "Bearer sk-test"


def test_fetch_provider_models_http_error(monkeypatch):
    monkeypatch.setattr(
        "src.utils.llm_client.requests.get",
        lambda url, headers=None, timeout=None: FakeResponse(
            status_code=401, data={"error": "invalid key"}
        ),
    )
    with pytest.raises(RuntimeError, match="401"):
        fetch_provider_models("https://example.com/v1", "bad")


def test_fetch_provider_models_network_error(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        raise ConnectionError("network down")

    monkeypatch.setattr("src.utils.llm_client.requests.get", fake_get)
    with pytest.raises(RuntimeError, match="network down"):
        fetch_provider_models("https://example.com/v1", "sk")


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
                        "model": "deepseek-v4-flash",
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
async def test_handle_llm_request_uses_preset_provider(monkeypatch):
    captured = {}

    async def fake_call(**kwargs):
        captured.update(kwargs)
        return {"content": "ok", "usage": None, "response_time_s": 0.1}

    monkeypatch.setattr("src.network.ws_transport.call_llm_api_async", fake_call)
    monkeypatch.setattr("src.network.ws_transport.fetch_llm_providers", lambda base_url: PRESETS)
    transport = WsTransport(
        "wss://example.com",
        username_getter=lambda: "u",
        token_getter=lambda: "t",
        api_key_getter=lambda: "sk-user",
        provider_getter=lambda: "DeepSeek",
        model_getter=lambda: None,
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
    # 必须使用用户预设的 base_url 与 model，而不是服务端下发的 url/model
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
    monkeypatch.setattr("src.network.ws_transport.fetch_llm_providers", lambda base_url: PRESETS)
    transport = WsTransport(
        "wss://example.com",
        username_getter=lambda: "u",
        token_getter=lambda: "t",
        api_key_getter=lambda: "sk-user",
        provider_getter=lambda: "DeepSeek",
        model_getter=lambda: "deepseek-reasoner",
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
    assert captured["payload"]["model"] == "deepseek-reasoner"
