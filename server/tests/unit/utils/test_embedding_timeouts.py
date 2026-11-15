"""Provider failures are bounded, retryable when transient, and cancellable."""

import asyncio
import json
import time
from types import SimpleNamespace

import httpx
import pytest

from src.infrastructure.models.llm.embedding import EmbeddingUnavailable, SiliconFlowEmbeddings


def transport(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))


@pytest.fixture
def advance_retry_wait(monkeypatch):
    from src.infrastructure.models.llm import embedding

    async def elapsed(_delay):
        await asyncio.sleep(0)

    monkeypatch.setattr(embedding, "asyncio", SimpleNamespace(**{**vars(asyncio), "sleep": elapsed}))


def test_transient_failure_recovers_and_batch_preserves_input_order(monkeypatch, advance_retry_wait):
    calls = []

    async def provider(request):
        calls.append(json.loads(request.content)["input"])
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"data": [
            {"index": 1, "embedding": [2.0]}, {"index": 0, "embedding": [1.0]},
        ]})

    transport(monkeypatch, provider)
    assert SiliconFlowEmbeddings(api_key="test").embed_documents(["a", "b"]) == [[1.0], [2.0]]
    assert len(calls) == 2


@pytest.mark.parametrize("status,attempts", [(401, 1), (400, 1), (429, 3), (503, 3)])
def test_failed_request_has_finite_retries_and_safe_diagnostics(monkeypatch, advance_retry_wait, status, attempts):
    calls = []

    async def provider(request):
        calls.append(request)
        return httpx.Response(status, text="secret input")

    transport(monkeypatch, provider)
    with pytest.raises(EmbeddingUnavailable) as error:
        SiliconFlowEmbeddings(api_key="secret key").embed_query("private input")
    assert len(calls) == attempts
    assert error.value.status_code == status
    assert "secret" not in str(error.value) and "private" not in str(error.value)


@pytest.mark.asyncio
async def test_real_stalled_socket_is_closed_within_request_deadline(monkeypatch):
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    connected, closed = asyncio.Event(), asyncio.Event()

    async def provider(reader, writer):
        try:
            await reader.readuntil(b"\r\n\r\n")
            connected.set()
            await reader.read()  # consume request body and wait for client EOF, never respond
        finally:
            writer.close()
            await writer.wait_closed()
            closed.set()

    server = await asyncio.start_server(provider, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    embeddings = SiliconFlowEmbeddings(
        api_key="test", base_url=f"http://127.0.0.1:{port}",
        request_timeout_seconds=0.15, total_timeout_seconds=2, max_attempts=1,
    )
    started = time.monotonic()
    async with server:
        with pytest.raises(EmbeddingUnavailable):
            await asyncio.to_thread(embeddings.embed_query, "hello")
        await asyncio.wait_for(closed.wait(), 1)
    assert connected.is_set()
    assert time.monotonic() - started < 2


@pytest.mark.asyncio
async def test_total_budget_cancels_request_and_explicit_cancel_does_not_retry(monkeypatch):
    entered = asyncio.Event()
    exited = asyncio.Event()
    calls = []

    async def provider(request):
        calls.append(request)
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            exited.set()

    transport(monkeypatch, provider)
    client = SiliconFlowEmbeddings(api_key="test", total_timeout_seconds=0.1)
    with pytest.raises(EmbeddingUnavailable, match="total_timeout"):
        await client.aembed_documents(["a", "b"])
    assert exited.is_set() and len(calls) == 1
    entered.clear()
    exited.clear()
    task = asyncio.create_task(client.aembed_documents(["a"]))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert exited.is_set() and len(calls) == 2
