"""Public adapter boundaries: raw messages, network completion, and protocol ACK."""

import asyncio
import json

import pytest

from src.adapter.websocket.chat import WebSocketAdapter
from src.adapter.websocket.connection import AdapterConnection
from src.web.websocket._adapter_io import _receive_message, _send_pump
from tests.integration.websocket.test_call_websocket_adapter import (
    BlockingSpeechFactory,
    call_adapter,
    manager,
    resume_message,
    start_message,
)
from tests.integration.websocket.test_websocket_adapter import Endpoint, end, output


class _Manager:
    def __init__(self):
        self.stage = Endpoint()
        self.disconnected = []

    async def try_to_get_stage(self, **kwargs):
        assert not hasattr(kwargs["connection"], "websocket")
        return self.stage

    async def disconnect(self, connection):
        self.disconnected.append(connection)


async def _chat():
    adapter = WebSocketAdapter()
    stages = _Manager()
    adapter.initialize(stages)
    connection = await adapter.open(user_id="user", connection_id=object(), capabilities=frozenset({"negative_ack_v1"}))
    ready = await adapter.next_output(connection)
    assert json.loads(ready.message)["type"] == "chat.ready"
    adapter.complete_output(connection, ready.delivery_id)
    return adapter, connection, stages


@pytest.mark.asyncio
async def test_chat_raw_input_ack_and_duplicate_key_rejection():
    adapter, connection, stages = await _chat()
    assert isinstance(connection, AdapterConnection)
    assert not hasattr(connection, "stage")
    raw = '{"type":"user_text","client_msg_id":"one","payload":{"message":"hello"}}'
    try:
        assert await adapter.receive(connection, raw) is None
        ack = await adapter.next_output(connection)
        assert json.loads(ack.message)["payload"]["ok"] is True
        assert len(stages.stage.stimuli) == 1
        adapter.complete_output(connection, ack.delivery_id)
        await adapter.receive(connection, '{"type":"hb_ping","type":"call.switch_prepare"}')
        rejection = await adapter.next_output(connection)
        assert json.loads(rejection.message)["payload"]["code"] == "BAD_JSON"
        assert len(stages.stage.stimuli) == 1
    finally:
        await adapter.close()


@pytest.mark.asyncio
async def test_switch_control_checks_original_size_before_normalizing_json():
    adapter, connection, _ = await _chat()
    try:
        raw = " " * 16384 + json.dumps(
            {
                "protocol": "call.v1",
                "type": "call.switch_prepare",
                "client_request_id": "switch",
                "character_id": "luotianyi",
            }
        )
        await adapter.receive(connection, raw)
        error = await adapter.next_output(connection)
        assert json.loads(error.message)["payload"]["code"] == "CONTROL_TOO_LARGE"
    finally:
        await adapter.close()


@pytest.mark.asyncio
async def test_chat_ready_precedes_output_produced_while_binding():
    adapter = WebSocketAdapter()
    stages = _Manager()
    adapter.initialize(stages)
    completions = []

    async def changed(state):
        from src.domain.agent import ConnectionState

        if state is ConnectionState.CONNECTED:
            completions.extend((adapter.output_sink.submit_output(output()), adapter.output_sink.submit_output(end())))
            await asyncio.sleep(0)

    stages.stage.connection_changed = changed
    connection = await adapter.open(user_id="user", connection_id=object())
    try:
        events = []
        for _ in range(3):
            delivery = await asyncio.wait_for(adapter.next_output(connection), 1)
            events.append(json.loads(delivery.message)["type"])
            adapter.complete_output(connection, delivery.delivery_id)
        assert events == ["chat.ready", "agent_message", "agent_message"]
        await asyncio.gather(*completions)
    finally:
        await adapter.close()


@pytest.mark.asyncio
async def test_chat_output_waits_for_send_and_waiter_cancel_does_not_withdraw_output():
    adapter, connection, _ = await _chat()
    try:
        waiting = adapter.output_sink.submit_output(output())
        terminal = adapter.output_sink.submit_output(end())
        frame = await adapter.next_output(connection)
        assert not waiting.done()
        waiting.cancel()
        adapter.complete_output(connection, frame.delivery_id)
        last = await adapter.next_output(connection)
        assert json.loads(last.message)["payload"]["is_final_package"]
        assert not terminal.done()
        adapter.complete_output(connection, last.delivery_id)
        await asyncio.wait_for(terminal, 1)
        assert waiting.cancelled()
    finally:
        await adapter.close()


@pytest.mark.asyncio
async def test_send_failure_fails_pending_and_old_feedback_cannot_complete_new_attachment():
    adapter, old, _ = await _chat()
    first = adapter.output_sink.submit_output(output())
    tail = adapter.output_sink.submit_output(end())
    frame = await adapter.next_output(old)
    adapter.complete_output(old, frame.delivery_id, error=ConnectionError("send failed"))
    for receipt in (first, tail):
        with pytest.raises(ConnectionError):
            await receipt
    await adapter.disconnect(old)
    new = await adapter.open(user_id="user", connection_id=object())
    ready = await adapter.next_output(new)
    adapter.complete_output(new, ready.delivery_id)
    waiting = adapter.output_sink.submit_output(output(execution_id="new"))
    last = adapter.output_sink.submit_output(end(execution_id="new"))
    sent = await adapter.next_output(new)
    adapter.complete_output(old, sent.delivery_id)
    assert not waiting.done()
    adapter.complete_output(new, sent.delivery_id)
    await waiting
    await adapter.disconnect(new)
    with pytest.raises(ConnectionError):
        await last
    await adapter.close()


@pytest.mark.asyncio
async def test_call_network_completion_does_not_ack_replay_and_reconnect_has_new_delivery_id():
    speech = BlockingSpeechFactory()
    stages, _ = manager(speech_factory=speech)
    adapter = call_adapter(stages)
    old = await adapter.open(user_id="user", connection_id=object(), initial_message=start_message())
    try:
        preparing = await adapter.next_output(old)
        body = json.loads(preparing.message)
        session = adapter._sessions[body["call_id"]]
        adapter.complete_output(old, preparing.delivery_id)
        assert session._delivery.server_ack_cursor == 0
        ack = await adapter.next_output(old)
        adapter.complete_output(old, ack.delivery_id)
        await adapter.receive(
            old, json.dumps({"protocol": "call.v1", "type": "ack", "call_id": session.call_id, "ack_seq": body["seq"]})
        )
        assert session._delivery.server_ack_cursor == body["seq"]
        await adapter.disconnect(old)
        new = await adapter.open(user_id="user", connection_id=object(), initial_message=start_message())
        retried = await adapter.next_output(new)
        assert retried.delivery_id not in {preparing.delivery_id, ack.delivery_id}
        state = adapter._bindings[new]._outbox
        adapter.complete_output(old, retried.delivery_id)
        assert retried.delivery_id in state._inflight
        adapter.complete_output(new, retried.delivery_id)
        assert not state._inflight
        await adapter.disconnect(new)
    finally:
        speech.release.set()
        await adapter.close()
        await stages.close()


@pytest.mark.asyncio
async def test_cancelled_network_send_reports_uncertain_failure():
    adapter, connection, _ = await _chat()
    waiting = adapter.output_sink.submit_output(output())
    tail = adapter.output_sink.submit_output(end())
    entered = asyncio.Event()

    class Socket:
        async def send_text(self, raw):
            entered.set()
            await asyncio.Event().wait()

    sending = asyncio.create_task(_send_pump(Socket(), adapter, connection))
    await entered.wait()
    sending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await sending
    for receipt in (waiting, tail):
        with pytest.raises(ConnectionError):
            await receipt
    await adapter.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ['{"type":"x","type":"y"}', b"\x00\x01"])
async def test_web_passes_original_message_without_protocol_parsing(raw):
    class Socket:
        async def receive(self):
            return {"type": "websocket.receive", "text" if isinstance(raw, str) else "bytes": raw}

    assert await _receive_message(Socket()) == raw


@pytest.mark.asyncio
async def test_disconnected_call_reader_cannot_consume_new_attachment_replay():
    speech = BlockingSpeechFactory()
    stages, _ = manager(speech_factory=speech)
    adapter = call_adapter(stages)
    old = await adapter.open(user_id="user", connection_id=object(), initial_message=start_message())
    try:
        first = await adapter.next_output(old)
        ack = await adapter.next_output(old)
        adapter.complete_output(old, first.delivery_id)
        adapter.complete_output(old, ack.delivery_id)
        waiting = asyncio.create_task(adapter.next_output(old))
        await asyncio.sleep(0)
        await adapter.disconnect(old)
        new = await adapter.open(user_id="user", connection_id=object(), initial_message=start_message())
        with pytest.raises(ConnectionError):
            await waiting
        new_ack = await asyncio.wait_for(adapter.next_output(new), 1)
        replay = await asyncio.wait_for(adapter.next_output(new), 1)
        assert json.loads(new_ack.message)["type"] == "ack"
        assert replay.message == first.message
        assert replay.delivery_id != first.delivery_id
        adapter.complete_output(new, new_ack.delivery_id)
        adapter.complete_output(new, replay.delivery_id)
        await adapter.disconnect(new)
    finally:
        speech.release.set()
        await adapter.close()
        await stages.close()


@pytest.mark.asyncio
async def test_resume_includes_output_produced_during_business_admission(monkeypatch):
    from src.domain.call import CallState
    from src.stage.call_stage import CallStateChanged

    speech = BlockingSpeechFactory()
    stages, _ = manager(speech_factory=speech)
    adapter = call_adapter(stages)
    old = await adapter.open(user_id="user", connection_id=object(), initial_message=start_message())
    try:
        preparing = await adapter.next_output(old)
        call_id = json.loads(preparing.message)["call_id"]
        adapter.complete_output(old, preparing.delivery_id)
        ack = await adapter.next_output(old)
        adapter.complete_output(old, ack.delivery_id)
        await adapter.disconnect(old)
        original = stages.try_to_get_stage
        session = adapter._sessions[call_id]

        async def admit_with_concurrent_output(**kwargs):
            result = await original(**kwargs)
            await adapter.submit_output(call_id, CallStateChanged(call_id, CallState.RINGING, "request-1"))
            return result

        monkeypatch.setattr(stages, "try_to_get_stage", admit_with_concurrent_output)
        new = await adapter.open(user_id="user", connection_id=object(), initial_message=resume_message(call_id))
        received = []
        for _ in range(3):
            delivery = await asyncio.wait_for(adapter.next_output(new), 1)
            received.append(json.loads(delivery.message))
            adapter.complete_output(new, delivery.delivery_id)
        assert received[0]["type"] == "call.resumed"
        assert [event["state"] for event in received[1:]] == ["preparing", "ringing"]
        assert [event["seq"] for event in received[1:]] == [1, 2]
        await adapter.disconnect(new)
    finally:
        speech.release.set()
        await adapter.close()
        await stages.close()


@pytest.mark.asyncio
async def test_client_model_request_and_response_use_the_adapter_channel():
    from src.adapter.websocket.chat.client_model_executor import ClientLLMExecutor

    executor = ClientLLMExecutor(timeout_seconds=1)
    adapter = WebSocketAdapter()
    adapter.initialize(_Manager(), client_executor=executor)
    connection = await adapter.open(user_id="user", connection_id=object())
    ready = await adapter.next_output(connection)
    adapter.complete_output(connection, ready.delivery_id)
    await adapter.receive(
        connection,
        json.dumps(
            {
                "type": "user_text",
                "client_msg_id": "one",
                "payload": {
                    "message": "hello",
                    "llm_mode": {"types": ["external"]},
                },
            }
        ),
    )
    ack = await adapter.next_output(connection)
    adapter.complete_output(connection, ack.delivery_id)
    request = asyncio.create_task(
        executor.delegate("user", module="reply", model_type="external", prompt="hi", params={})
    )
    try:
        delivery = await adapter.next_output(connection)
        body = json.loads(delivery.message)
        assert body["type"] == "llm_request"
        adapter.complete_output(connection, delivery.delivery_id)
        response = {"request_id": body["payload"]["request_id"], "content": "answer"}
        executor.on_llm_response(response, connection=object())
        assert not request.done()
        await adapter.receive(connection, json.dumps({"type": "llm_response", "payload": response}))
        assert (await request)["content"] == "answer"
    finally:
        request.cancel()
        await asyncio.gather(request, return_exceptions=True)
        await adapter.close()


@pytest.mark.asyncio
async def test_chat_binding_has_one_stage_and_detach_preserves_control_responses():
    adapter, handle, stages = await _chat()
    binding = adapter._bindings[handle]
    stage = stages.stage
    try:
        with pytest.raises(ValueError, match="already assigned"):
            await adapter._bind(Endpoint("second", "user", "another"), binding)
        assert binding.stage is stage
        await adapter.detach_stage_binding(stage, binding)
        assert not binding.is_closed
        assert not binding.submit(object())
        with pytest.raises(ValueError, match="already assigned"):
            await adapter._bind(stage, binding)
        # 解绑后原 WebSocket 仍能发送协议应答，但业务输入不得再交给 Stage。
        await adapter.receive(handle, '{"type":"user_text","client_msg_id":"late","payload":{"message":"hello"}}')
        rejection = await adapter.next_output(handle)
        assert json.loads(rejection.message)["payload"]["ok"] is False
        adapter.complete_output(handle, rejection.delivery_id)
        assert not stage.stimuli
        completion = binding.enqueue('{"type":"control"}')
        delivery = await adapter.next_output(handle)
        assert json.loads(delivery.message)["type"] == "control"
        assert not completion.done()
        adapter.complete_output(handle, delivery.delivery_id)
        await completion
        # 重连接入创建新 Binding，旧对象始终保持失效。
        new_handle = await adapter.open(user_id="user", connection_id=object())
        assert adapter._bindings[new_handle] is not binding
        assert not binding.submit(object())
    finally:
        await adapter.close()
    assert binding.is_closed
