"""真实流式 HTTP 读取与模块调用，避免把完整响应伪装成增量输出。"""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from src.infrastructure.models.llm.interface import OpenAIAPIInterface, RequestsAPIInterface
from src.infrastructure.models.llm.module import LLMModule


class Events(httpx.AsyncByteStream):
    def __init__(self, release, complete):
        self.release, self.complete, self.closed = release, complete, False

    async def __aiter__(self):
        yield b'data: {"choices":[{"delta":{"content":"first"}}]}\n\n'
        await self.release.wait()
        if self.complete:
            yield b'data: {"choices":[{"delta":{"content":"second"},"finish_reason":"stop"}]}\n\n'
            yield b'data: {"choices":[],"usage":{"total_tokens":9}}\n\ndata: [DONE]\n\n'

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["openai", "requests"])
@pytest.mark.parametrize("ending", ["success", "truncated", "cancelled"])
async def test_provider_stream_is_incremental_and_closes_on_all_exits(monkeypatch, kind, ending):
    release, first = asyncio.Event(), asyncio.Event()
    events = Events(release, ending == "success")
    requests = []

    async def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, stream=events)

    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        "src.infrastructure.models.llm.streaming.httpx.AsyncClient",
        lambda **kwargs: client_type(transport=httpx.MockTransport(handler), **kwargs),
    )
    config = {
        "base_url": "https://example.test/v1",
        "url": "https://example.test/v1/chat/completions",
        "model": "test",
        "api_key": "",
    }
    interface = (OpenAIAPIInterface if kind == "openai" else RequestsAPIInterface)(config)
    interface.api_key = "test-key"
    module = LLMModule("reply", {}, SimpleNamespace(render=lambda **kwargs: "prompt"), interface, stream=True)
    parts = []

    async def delta(text):
        parts.append(text)
        first.set()

    task = asyncio.create_task(module.generate_response(on_delta=delta))
    await asyncio.wait_for(first.wait(), 1)
    assert not task.done()
    assert parts == ["first"]
    if ending == "cancelled":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        release.set()
        if ending == "truncated":
            with pytest.raises(RuntimeError, match="意外断开"):
                await task
        else:
            assert await task == "firstsecond"
            assert module.recent_response["usage"] == {"total_tokens": 9}
    assert events.closed
    assert len(requests) == 1
    assert requests[0]["stream"] is True
