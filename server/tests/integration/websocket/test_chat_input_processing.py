"""Input processing is not admission; successful business ACK follows submit."""

import asyncio
import json
from types import SimpleNamespace

import pytest

import src.domain.agent as d
from src.adapter.websocket.chat import WebSocketAdapter
from src.adapter.websocket.chat._input import _process_input
from src.adapter.websocket.chat._messages import _WSMessage
from src.adapter.websocket.chat._voice_upload_helper import _VoiceUploadAssembler
from src.infrastructure.media import PermanentMediaStore
from tests.integration.websocket.test_adapter_network_boundary import _chat
from tests.integration.websocket.test_voice_upload import Stage, event, m4a_bytes, upload_events


@pytest.mark.asyncio
async def test_concurrent_retry_cannot_pass_dedup_before_first_admission(monkeypatch):
    from src.adapter.websocket.chat import adapter as module

    adapter, handle, manager = await _chat()
    process = module._process_input
    entered, release = asyncio.Event(), asyncio.Event()

    async def blocked(*args):
        entered.set()
        await release.wait()
        return await process(*args)

    monkeypatch.setattr(module, "_process_input", blocked)
    raw = json.dumps({"type": "user_text", "client_msg_id": "same", "payload": {"text": "hello"}})
    first = asyncio.create_task(adapter.receive(handle, raw))
    second = None
    try:
        await asyncio.wait_for(entered.wait(), 1)
        second = asyncio.create_task(adapter.receive(handle, raw))
        await asyncio.sleep(0)
        release.set()
        await asyncio.gather(first, second)
        assert len(manager.stage.stimuli) == 1
        packets = []
        for _ in range(2):
            delivery = await adapter.next_output(handle)
            packets.append(json.loads(delivery.message)["payload"])
            adapter.complete_output(handle, delivery.delivery_id)
        assert [packet.get("duplicate", False) for packet in packets] == [False, True]
    finally:
        release.set()
        await asyncio.gather(first, *([second] if second else []), return_exceptions=True)
        await adapter.close()


@pytest.mark.asyncio
async def test_input_returns_stimulus_and_status_without_delivering(tmp_path):
    store = PermanentMediaStore({"root": str(tmp_path / "media")})
    helper = _VoiceUploadAssembler(store)

    async def process(value):
        message = _WSMessage(value["type"], value["payload"], value["client_msg_id"])
        return await _process_input(message, "user", "luotianyi", store, helper)

    stimulus, status = await process({"type": "user_text", "client_msg_id": "text", "payload": {"text": "hello"}})
    assert isinstance(stimulus, d.TextMessage) and status["state"] == "complete"
    stimulus, status = await process({"type": "user_text", "client_msg_id": "bad", "payload": {}})
    assert stimulus is None and status["state"] == "error"

    _, events = upload_events(m4a_bytes())
    stimulus, status = await process(events[0])
    assert isinstance(stimulus, d.VoiceRecordingCommitted) and status["state"] == "complete"
    assert not helper._uploads  # Preparing a stimulus has not admitted the upload.
    await helper.commit(object())
    stimulus, status = await process(events[1])
    assert stimulus is None and status["state"] == "partial"
    stimulus, status = await process(events[1])
    assert stimulus is None and status["state"] == "duplicate"
    for value in events[2:-1]:
        stimulus, status = await process(value)
        assert stimulus is None and status["state"] == "partial"
    stimulus, status = await process(events[-1])
    assert isinstance(stimulus, d.VoiceMessage) and status["state"] == "complete"
    assert not helper._completed
    assert not list((tmp_path / "media").glob("*/ingress_receipt.json"))
    helper.discard_prepared()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rejected_type", [d.TextMessage, d.VoiceRecordingCommitted, d.VoiceMessage, d.VoiceUploadFailed]
)
async def test_ack_and_completion_receipt_require_successful_submit(tmp_path, rejected_type):
    adapter = WebSocketAdapter({"media_store": {"root": str(tmp_path / "media")}})
    stage = Stage("user")
    submit = stage.submit
    rejected = [True]

    def accept(stimulus):
        if rejected[0] and isinstance(stimulus, rejected_type):
            return False
        return submit(stimulus)

    stage.submit = accept
    manager = SimpleNamespace(
        try_to_get_stage=lambda **kwargs: asyncio.sleep(0, result=stage),
        disconnect=lambda connection: asyncio.sleep(0),
    )
    adapter.initialize(manager)
    handle = await adapter.open(user_id="user", connection_id=object(), capabilities=frozenset({"negative_ack_v1"}))

    async def receive_ack(value):
        await adapter.receive(handle, json.dumps(value))
        delivery = await adapter.next_output(handle)
        packet = json.loads(delivery.message)
        adapter.complete_output(handle, delivery.delivery_id)
        return packet["payload"]

    ready = await adapter.next_output(handle)
    adapter.complete_output(handle, ready.delivery_id)
    upload_id, events = upload_events(m4a_bytes())
    if rejected_type is d.TextMessage:
        before, last = [], {"type": "user_text", "client_msg_id": "text", "payload": {"text": "hello"}}
    elif rejected_type is d.VoiceRecordingCommitted:
        before, last = [], events[0]
    elif rejected_type is d.VoiceUploadFailed:
        before, last = events[:1], event("abort", upload_id)
    else:
        before, last = events[:-1], events[-1]
    try:
        for value in before:
            assert (await receive_ack(value))["ok"] is True
        failure = await receive_ack(last)
        assert failure["ok"] is False and failure["code"] == "OVERLOADED"
        assert not any(isinstance(item, rejected_type) for item in stage.stimuli)
        assert not list((tmp_path / "media").glob("*/ingress_receipt.json"))
        rejected[0] = False
        success = await receive_ack(last)
        assert success["ok"] is True and not success.get("duplicate")
        assert sum(isinstance(item, rejected_type) for item in stage.stimuli) == 1
        await receive_ack(last)
        assert sum(isinstance(item, rejected_type) for item in stage.stimuli) == 1
    finally:
        await adapter.close()
