"""桌面端把供应商增量逐段发回原连接；取消时关闭 HTTP 流。"""

import asyncio
import json

import httpx
import pytest

from src.network.ws_transport import WsTransport
from src.utils.llm_client import call_llm_api_async


@pytest.mark.parametrize("cancel", [False, True])
def test_stream_reaches_websocket_before_completion_and_closes(monkeypatch, cancel):
    async def run():
        first, release = asyncio.Event(), asyncio.Event()
        sent = []

        class Stream(httpx.AsyncByteStream):
            closed = False

            async def __aiter__(self):
                event = {"choices": [{"delta": {"content": "第一句话。"}}]}
                yield ("data: " + json.dumps(event) + "\n\n").encode()
                await release.wait()
                yield b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'

            async def aclose(self):
                self.closed = True

        stream = Stream()
        client_type = httpx.AsyncClient
        monkeypatch.setattr("src.utils.llm_client.httpx.AsyncClient", lambda **kwargs: client_type(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=stream)), **kwargs
        ))

        class Socket:
            async def send(self, text):
                sent.append(json.loads(text)["payload"])
                first.set()

        async def execute(payload, on_delta=None):
            result = await call_llm_api_async(
                url="https://example.test", api_key="test-key", payload={"stream": True}, on_delta=on_delta
            )
            return {"request_id": payload["request_id"], **result}

        transport = WsTransport("http://localhost", lambda: "u", lambda: "token")
        transport._llm_request_listener = execute
        task = asyncio.create_task(transport._handle_llm_request(Socket(), {"request_id": "r", "stream": True}))
        await asyncio.wait_for(first.wait(), 1)
        assert sent == [{"request_id": "r", "sequence": 0, "delta": "第一句话。"}]
        assert not task.done()
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert len(sent) == 1
        else:
            release.set()
            await task
            assert sent[-1]["content"] == "第一句话。"
            assert sent[-1]["sequence"] == 1
            assert sent[-1]["done"] is True
        assert stream.closed

    asyncio.run(run())
