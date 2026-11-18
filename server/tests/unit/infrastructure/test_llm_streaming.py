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


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 429, 200])
async def test_provider_error_records_diagnostics_without_format_error_or_content(
    monkeypatch, tmp_path, caplog, capture_project_log, status
):
    from src.infrastructure.observability import (
        ObservabilityService,
        get_observability_service,
        set_observability_service,
    )
    from src.infrastructure.models.llm.errors import ProviderStreamError

    payload = {
        "error": {
            "code": "DataInspectionFailed" if status != 429 else "RateLimitExceeded",
            "type": "invalid_request_error",
            "message": "private prompt and secret-key",
        },
        "request_id": "provider-request-123",
    }

    async def handler(request):
        if status == 200:
            return httpx.Response(status, content=("data: " + json.dumps(payload) + "\n\n").encode())
        return httpx.Response(status, json=payload)

    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        "src.infrastructure.models.llm.streaming.httpx.AsyncClient",
        lambda **kwargs: client_type(transport=httpx.MockTransport(handler), **kwargs),
    )
    interface = OpenAIAPIInterface({"base_url": "https://example.test/v1", "api_key": "", "model": "test"})
    interface.api_key = "secret-key"
    module = LLMModule("reply", {}, SimpleNamespace(render=lambda **kwargs: "private prompt"), interface, stream=True)
    capture_project_log(module.logger.name)
    store = ObservabilityService({"db_path": str(tmp_path / "metrics.db")})
    previous = get_observability_service()
    set_observability_service(store)
    try:
        with pytest.raises(ProviderStreamError if status == 200 else httpx.HTTPStatusError):
            await module.generate_response()
        row = store._query_all("SELECT * FROM llm_call_metrics")[0]
        assert row["success"] == 0
        assert "provider-request-123" in row["error_message"] and payload["error"]["code"] in row["error_message"]
        rendered = " ".join(record.getMessage() for record in caplog.records)
        assert "provider-request-123" in rendered and payload["error"]["code"] in rendered
        assert "private prompt" not in rendered + row["error_message"]
        assert "secret-key" not in rendered + row["error_message"]
    finally:
        set_observability_service(previous)
        store.close()


def test_content_inspection_wrapper_preserves_provider_identifiers():
    from src.infrastructure.models.llm.errors import provider_error_details
    from src.infrastructure.models.llm.interface import LLMContentInspectionError

    response = httpx.Response(
        400,
        request=httpx.Request("POST", "https://example.test"),
        json={"code": "DataInspectionFailed", "request_id": "sdk-request", "message": "private input"},
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as cause:
        try:
            raise LLMContentInspectionError("private input") from cause
        except LLMContentInspectionError as error:
            detail = provider_error_details(error)
    assert "DataInspectionFailed" in detail and "sdk-request" in detail and "400" in detail
    assert "private input" not in detail
