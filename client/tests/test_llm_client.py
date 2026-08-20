"""桌面端 LLM HTTP 工具测试。"""

import pytest

from src.utils.llm_client import (
    build_chat_completions_payload,
    call_llm_api,
    fetch_client_model_types,
    probe_llm_config,
)


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


def test_build_payload_passes_through_extra_params():
    payload = build_chat_completions_payload(
        prompt="hi",
        model="m",
        params={
            "max_tokens": 1024,
            "stop": ["END"],
            "presence_penalty": 0.5,
            "frequency_penalty": 0.3,
        },
    )
    assert payload["max_tokens"] == 1024
    assert payload["stop"] == ["END"]
    assert payload["presence_penalty"] == 0.5
    assert payload["frequency_penalty"] == 0.3


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
        captured.update(url=url, headers=headers, json=json)
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


def test_fetch_client_model_types_success(monkeypatch):
    captured = {}

    def fake_get(url, timeout=None):
        captured["url"] = url
        return FakeResponse(
            data={
                "types": [
                    {
                        "type": "对话模型",
                        "providers": [
                            {
                                "name": "DeepSeek",
                                "base_url": "https://api.deepseek.com/v1",
                                "models": [{"id": "deepseek-chat"}],
                            }
                        ],
                    }
                ]
            }
        )

    monkeypatch.setattr("src.utils.llm_client.requests.get", fake_get)
    types = fetch_client_model_types("https://server.example.com")
    assert types[0]["type"] == "对话模型"
    assert types[0]["providers"][0]["name"] == "DeepSeek"
    assert captured["url"] == "https://server.example.com/llm/providers"


def test_fetch_client_model_types_error(monkeypatch):
    monkeypatch.setattr(
        "src.utils.llm_client.requests.get",
        lambda url, timeout=None: FakeResponse(status_code=500),
    )
    with pytest.raises(RuntimeError, match="500"):
        fetch_client_model_types("https://server.example.com")


def test_probe_llm_config_builds_probe_payload(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured.update(url=url, headers=headers, json=json, timeout=timeout)
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
    assert captured["json"]["max_tokens"] == 8
    assert captured["json"]["temperature"] == 0
    assert captured["json"]["enable_thinking"] is True
    assert captured["json"]["response_format"] == {"type": "json_object"}
    assert captured["timeout"] == 15.0


def test_probe_llm_config_plain_ping(monkeypatch):
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
    assert captured["json"]["messages"][0]["content"] == "ping"
    assert "enable_thinking" not in captured["json"]
    assert "response_format" not in captured["json"]


def test_probe_llm_config_raises_on_provider_error(monkeypatch):
    monkeypatch.setattr(
        "src.utils.llm_client.requests.post",
        lambda url, headers=None, json=None, timeout=None: FakeResponse(
            status_code=400,
            data={"error": {"message": "unsupported switch"}},
        ),
    )
    with pytest.raises(RuntimeError, match="400"):
        probe_llm_config(
            base_url="https://example.com/v1",
            api_key="sk",
            model="m",
            flags={"use_json": True},
        )
