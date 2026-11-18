"""Provider failures are bounded, retryable when transient, and cancellable."""

import asyncio
import json
import threading
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


@pytest.fixture
async def stalled_socket(monkeypatch):
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    state = SimpleNamespace(
        accepted=False,
        header=False,
        eof=False,
        partial=None,
        header_received=asyncio.Event(),
        closed=asyncio.Event(),
    )
    handlers, writers = set(), set()

    async def provider(reader, writer):
        handlers.add(asyncio.current_task())
        writers.add(writer)
        state.accepted = True
        try:
            await reader.readuntil(b"\r\n\r\n")
            state.header = True
            state.header_received.set()
            await reader.read()  # 不回响应，必须由客户端关闭后得到EOF。
            state.eof = True
        except asyncio.IncompleteReadError as error:
            state.partial, state.eof = len(error.partial), True
        finally:
            writer.close()
            await writer.wait_closed()
            writers.discard(writer)
            state.closed.set()

    server = await asyncio.start_server(provider, "127.0.0.1", 0)
    state.url = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
    state.handlers = handlers

    async def close():
        server.close()
        await server.wait_closed()
        for writer in tuple(writers):
            writer.close()
        if handlers:
            await asyncio.wait_for(asyncio.gather(*handlers), 1)

    state.close = close
    try:
        yield state
    finally:
        await close()


def observe_client(monkeypatch, trace):
    original = httpx.AsyncClient

    control = SimpleNamespace(loop=None, task=None, gate=None)

    class ObservedClient(original):
        async def post(self, *args, **kwargs):
            control.loop, control.task = asyncio.get_running_loop(), asyncio.current_task()
            return await super().post(*args, extensions={"trace": trace}, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", ObservedClient)
    return control


async def wait_sync_request(embeddings, socket, control, timeout=3):
    control.worker_exited = threading.Event()

    def invoke():
        try:
            return embeddings.embed_query("hello")
        finally:
            control.worker_exited.set()  # 同步调用及其asyncio.run真正退出，不是包装Task被取消。

    worker = asyncio.create_task(asyncio.to_thread(invoke))
    try:
        return await asyncio.wait_for(asyncio.shield(worker), timeout)
    finally:
        if not worker.done():

            def release():
                if control.gate is not None:
                    control.gate.set()
                if control.task is not None and not control.task.done():
                    control.task.cancel()

            if control.loop is not None and not control.loop.is_closed():
                control.loop.call_soon_threadsafe(release)
            try:
                await socket.close()  # 只在异常看门路径强制关闭；正常路径仍须自行得到真实EOF。
            finally:
                done, _ = await asyncio.wait({worker}, timeout=1)
                assert done and control.worker_exited.is_set(), "client thread did not actually finish cleanup"
        assert control.worker_exited.is_set()
        await asyncio.gather(worker, return_exceptions=True)  # 只取已经结束的结果，不取消to_thread包装冒充join。


@pytest.mark.asyncio
@pytest.mark.parametrize("gate_headers", [False, True], ids=["no-gate", "headers-gated"])
async def test_real_socket_request_deadline_classifies_early_close(monkeypatch, stalled_socket, gate_headers):
    async def trace(name, _info):
        if gate_headers and name == "http11.send_request_headers.started":
            control.gate = asyncio.Event()
            await control.gate.wait()

    control = observe_client(monkeypatch, trace)
    embeddings = SiliconFlowEmbeddings(
        api_key="test",
        base_url=stalled_socket.url,
        request_timeout_seconds=0.15,
        total_timeout_seconds=2,
        max_attempts=1,
    )
    started = time.monotonic()
    with pytest.raises(EmbeddingUnavailable) as failed:
        await wait_sync_request(embeddings, stalled_socket, control)
    assert failed.value.reason == "TimeoutError" and failed.value.attempts == 1
    if stalled_socket.accepted:
        await asyncio.wait_for(stalled_socket.closed.wait(), 1)
        assert stalled_socket.eof
        assert all(task.done() for task in stalled_socket.handlers)
    if gate_headers:
        assert not stalled_socket.header
    # 完整header或TCP接受都不是必须在150ms内完成的承诺。
    assert time.monotonic() - started < 2


@pytest.mark.asyncio
async def test_request_watchdog_releases_gate_and_joins_real_worker(monkeypatch, stalled_socket):
    entered = threading.Event()

    async def trace(name, _info):
        if name == "http11.send_request_headers.started":
            control.gate = asyncio.Event()
            entered.set()
            print("WATCHDOG_GATE_ENTERED", flush=True)
            while not control.gate.is_set():
                try:
                    await control.gate.wait()
                except asyncio.CancelledError:
                    pass  # 仅此坏路径：计时取消不结束处理，必须由测试owner放门。

    control = observe_client(monkeypatch, trace)
    embeddings = SiliconFlowEmbeddings(
        api_key="test",
        base_url=stalled_socket.url,
        request_timeout_seconds=0.15,
        total_timeout_seconds=2,
        max_attempts=1,
    )
    with pytest.raises(asyncio.TimeoutError):
        await wait_sync_request(embeddings, stalled_socket, control, timeout=0.5)
    assert entered.is_set()
    assert stalled_socket.closed.is_set()
    assert all(task.done() for task in stalled_socket.handlers)
    assert control.loop.is_closed() and control.worker_exited.is_set()


@pytest.mark.asyncio
async def test_real_response_stall_is_cancelled_at_original_request_deadline(monkeypatch, stalled_socket):
    main_loop = asyncio.get_running_loop()
    receiving = asyncio.Event()
    clock = {"elapsed": 0.0}
    control = {}
    stopped = threading.Event()
    result = []

    async def trace(name, _info):
        if name == "http11.receive_response_headers.started":
            loop = asyncio.get_running_loop()
            control["timers"] = [
                (round(handle.when() - control["origin"], 6), type(handle._callback).__name__)
                for handle in loop._scheduled
                if not handle.cancelled()
            ]
            main_loop.call_soon_threadsafe(receiving.set)

    observe_client(monkeypatch, trace)
    embeddings = SiliconFlowEmbeddings(
        api_key="test",
        base_url=stalled_socket.url,
        request_timeout_seconds=0.15,
        total_timeout_seconds=2,
        max_attempts=1,
    )

    def client_thread():
        loop = asyncio.new_event_loop()
        original_time = loop.time
        origin = original_time()
        loop.time = lambda: origin + clock["elapsed"]
        control.update(loop=loop, origin=origin, resolution=loop._clock_resolution)
        task = loop.create_task(embeddings.aembed_documents(["hello"]))
        control["task"] = task
        try:
            loop.run_until_complete(task)
        except BaseException as error:
            result.append(error)
            control["error_elapsed"] = clock["elapsed"]
        finally:
            loop.time = original_time
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.run_until_complete(loop.shutdown_default_executor())
            loop.close()
            stopped.set()

    async def advance(elapsed):
        changed = asyncio.Event()

        def move():
            clock["elapsed"] = elapsed
            control["loop"].call_soon(lambda: main_loop.call_soon_threadsafe(changed.set))

        control["loop"].call_soon_threadsafe(move)
        await asyncio.wait_for(changed.wait(), 1)

    thread = threading.Thread(target=client_thread, name="embedding-deadline-test", daemon=True)
    thread.start()
    try:
        await asyncio.wait_for(stalled_socket.header_received.wait(), 2)
        await asyncio.wait_for(receiving.wait(), 2)
        before_deadline = 0.15 - 2 * control["resolution"]
        assert 0 < before_deadline < 0.15
        await advance(before_deadline)
        assert not stopped.is_set() and not stalled_socket.closed.is_set()
        assert clock["elapsed"] == before_deadline  # 同一起点，且离到期超过平台时钟分辨率。
        assert any(abs(when - 0.15) < 0.000001 for when, _ in control["timers"])
        await advance(0.16)
        assert await asyncio.to_thread(stopped.wait, 1)
        await asyncio.wait_for(stalled_socket.closed.wait(), 1)
        assert len(result) == 1 and isinstance(result[0], EmbeddingUnavailable)
        assert result[0].reason == "TimeoutError" and result[0].attempts == 1
        assert control["error_elapsed"] == 0.16  # 原异常在finally恢复真实时钟前已经出现。
        assert stalled_socket.header and stalled_socket.eof
    finally:
        if not stopped.is_set() and "loop" in control:
            control["loop"].call_soon_threadsafe(control["task"].cancel)
        await asyncio.to_thread(thread.join, 2)
        assert not thread.is_alive()
        assert control["loop"].is_closed()


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
