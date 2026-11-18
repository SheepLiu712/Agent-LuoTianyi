"""客户端模型分片在最终响应前到达，序号、归属和取消不会导致重播。"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from src.adapter.websocket.chat.client_model_executor import ClientLLMError, ClientLLMExecutor
from src.infrastructure.models.llm.module import LLMModule


class Connection:
    client_mode = {"types": ["main_chat"], "stream": True}

    def __init__(self):
        self.events = []
        self.requested = asyncio.Event()

    async def send(self, event):
        self.events.append(json.loads(event))
        self.requested.set()


def setup():
    connection = Connection()
    executor = ClientLLMExecutor(timeout_seconds=2)
    executor.bind(lambda _: connection)
    interface = SimpleNamespace(default_parameters={}, get_interface_info=lambda: {"model": "unused"})
    module = LLMModule(
        "reply",
        {"client_model_type": "main_chat"},
        SimpleNamespace(render=lambda **_: "prompt"),
        interface,
        client_llm_executor=executor,
        stream=True,
    )
    return connection, executor, module


@pytest.mark.asyncio
async def test_module_delivers_client_delta_before_final_and_keeps_usage(monkeypatch):
    connection, executor, module = setup()
    monkeypatch.setattr("src.infrastructure.models.llm.module.get_trace_context", lambda: {"user_id": "u"})
    delivered, first = [], asyncio.Event()

    async def delta(text):
        delivered.append(text)
        first.set()

    task = asyncio.create_task(module.generate_response(on_delta=delta))
    await connection.requested.wait()
    request_id = connection.events[0]["payload"]["request_id"]
    assert connection.events[0]["payload"]["stream"] is True
    executor.on_llm_response({"request_id": request_id, "sequence": 0, "delta": "旧连接"}, connection=object())
    executor.on_llm_response({"request_id": request_id, "sequence": 0, "delta": "第一句话。"}, connection=connection)
    await asyncio.wait_for(first.wait(), 1)
    assert delivered == ["第一句话。"]
    assert not task.done()
    executor.on_llm_response({"request_id": request_id, "sequence": 1, "delta": "第二句。"}, connection=connection)
    executor.on_llm_response(
        {
            "request_id": request_id,
            "sequence": 2,
            "done": True,
            "content": "第一句话。第二句。",
            "usage": {"total_tokens": 12},
        },
        connection=connection,
    )
    assert await task == "第一句话。第二句。"
    assert delivered == ["第一句话。", "第二句。"]
    assert module.recent_response["usage"] == {"total_tokens": 12}
    assert executor._pending == executor._streams == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["duplicate", "gap", "final_mismatch", "cancel", "disconnect"])
async def test_partial_client_stream_never_restarts_after_failure(failure):
    connection, executor, _ = setup()
    delivered, first = [], asyncio.Event()

    async def delta(text):
        delivered.append(text)
        first.set()

    task = asyncio.create_task(
        executor.delegate(
            "u", module="reply", model_type="main_chat", prompt="prompt", params={}, stream=True, on_delta=delta
        )
    )
    await connection.requested.wait()
    request_id = connection.events[0]["payload"]["request_id"]
    executor.on_llm_response({"request_id": request_id, "sequence": 0, "delta": "已经交付"}, connection=connection)
    await asyncio.wait_for(first.wait(), 1)
    if failure == "cancel":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    elif failure == "disconnect":
        executor.clear_user("u", connection)
        with pytest.raises(Exception, match="disconnected"):
            await task
    else:
        packet = {"request_id": request_id, "sequence": 0 if failure == "duplicate" else 2, "delta": "重复"}
        if failure == "final_mismatch":
            packet = {"request_id": request_id, "sequence": 1, "done": True, "content": "不同文本"}
        executor.on_llm_response(packet, connection=connection)
        with pytest.raises(ClientLLMError):
            await task
    assert delivered == ["已经交付"]
    assert len([event for event in connection.events if event["type"] == "llm_request"]) == 1
    assert executor._pending == executor._streams == {}
    if failure != "disconnect":
        assert connection.events[-1]["type"] == "llm_cancel"
