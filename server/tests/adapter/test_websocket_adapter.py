"""通过 adapter 公共接口验证真实 SAY、协议兼容、隔离和断线收尾。"""
import asyncio
import base64
from dataclasses import replace
import io
import json
from types import SimpleNamespace
import wave

from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
import pytest

import src.domain.agent as d
from src.domain.stage import AgentPresentationChanged, AgentPresentationState, CancelDelivery
from src.adapter.websocket import WebSocketAdapter
from src.agent import Agent
from src.agent.handlers.action.router import ActionRouter
from src.agent.handlers.action.say import SayHandler
from src.agent.skills.expression.speaking import SpeakingSkill
from src.capabilities.speech.streaming import AsyncTTS
from src.resources.prepared_speech import PreparedSpeechResources
from src.system.user_interface.types import WSMessage
from src.system.user_interface.websocket_service import ChatEventAcceptance, WebSocketConnection, WebSocketService


class Socket:
    def __init__(self):
        self.events = []
        self.fail = False
        self.gate = None
        self.entered = asyncio.Event()

    async def send_json(self, event):
        self.entered.set()
        if self.gate is not None:
            await self.gate.wait()
        if self.fail:
            raise ConnectionError("disconnected")
        self.events.append(event)


class Endpoint:
    """只替换 Stage，观察 adapter 交付的刺激和连接通知。"""
    def __init__(self, interaction_id="interaction", user_id="user", character_id="luotianyi"):
        self.interaction_id, self.user_id, self.character_id = interaction_id, user_id, character_id
        self.stimuli = []
        self.available = True
        self.stimulus_input_sink = self
        self.states = []

    def can_accept(self, stimulus):
        return self.available

    def submit(self, stimulus):
        self.stimuli.append(stimulus)
        return True

    async def connection_changed(self, state):
        self.states.append(state)


async def setup_output(adapter=None, interaction_id="interaction", user_id="user"):
    socket = Socket()
    connection = WebSocketConnection(socket, user_id, "用户")
    adapter = adapter or WebSocketAdapter()
    stage = Endpoint(interaction_id, user_id)
    await adapter.bind(stage, connection)
    return socket, connection, adapter, stage


class OutputPort:
    def __init__(self, adapter):
        self.adapter = adapter
        self.futures = []

    async def emit(self, value):
        self.futures.append(self.adapter.submit_output(value))
        return d.OutputReceipt(execution_id=value.execution_id, sequence_no=value.sequence_no,
                               status=d.OutputAcceptanceStatus.ACCEPTED)


def output(cls=d.TextFinalOutput, **changes):
    fields = dict(interaction_id="interaction", execution_id="execution", action_id="say",
                  sequence_no=0, delivery=d.OutputDelivery.CONVERSATION)
    if cls is d.TextFinalOutput:
        fields["text"] = "你好"
    fields.update(changes)
    return cls(**fields)


def wav_bytes():
    stream = io.BytesIO()
    with wave.open(stream, "wb") as audio:
        audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\x00\x01" * 60000)
    return stream.getvalue()


def agent_and_plan(tmp_path, *, prepared, delivery):
    data = wav_bytes()
    (tmp_path / "speech.wav").write_bytes(data)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([dict(name="speech", audio_path="speech.wav", text="", expression="")]), encoding="utf-8")
    calls = []

    def synthesize(text, tone, *, cancel_event):
        calls.append(text)
        yield data[:44]
        yield data[44:]

    skill = SpeakingSkill({}, AsyncTTS(SimpleNamespace(tts_module={
        "luotianyi": SimpleNamespace(stream_synthesize_speech_with_tone=synthesize),
    })))
    handler = SayHandler("luotianyi", skill, PreparedSpeechResources({"manifest": str(manifest)}))
    agent = Agent(character_id="luotianyi", action_router=ActionRouter([(d.ActionKind.SAY, handler)]))
    action = d.Say(action_id="say", content="你好", sound_content=None if prepared else "你好",
                   prepared_audio_ref=d.MediaRef(media_id="speech") if prepared else None,
                   tone=d.Tone(value="normal"), expression=d.ChangeExpression(expression_id="moemoe"), delivery=delivery)
    plan = d.ActionPlan(plan_id="plan", origin_request_id="request", plan_ordinal=0,
                        target_character_id="luotianyi", interaction_id="interaction",
                        basis_interaction_revision=1, source_stimulus_ids=("stimulus",), actions=(action,))
    return agent, plan, data, calls



def end(**changes):
    return output(d.MessageEndOutput, status=d.MessageEndStatus.COMPLETED, error_code=None, **changes)


@pytest.mark.asyncio
@pytest.mark.parametrize("prepared", [False, True])
@pytest.mark.parametrize("delivery", list(d.OutputDelivery))
async def test_real_say_protocol(tmp_path, prepared, delivery):
    agent, plan, expected, calls = agent_and_plan(tmp_path, prepared=prepared, delivery=delivery)
    socket, connection, adapter, stage = await setup_output()
    port = OutputPort(adapter)
    context = d.ExecutionContext(execution_id="execution", interaction_id="interaction",
                                 current_interaction_revision=1, cancellation=d.CancellationToken())
    try:
        report = await agent.realize_action_plan(plan, context, port)
        assert report.status is d.ExecutionStatus.COMPLETED
        await asyncio.gather(*port.futures)
        packets = [event["payload"] for event in socket.events]
        assert len({p["uuid"] for p in packets}) == 1
        assert [p["packet_sequence"] for p in packets] == list(range(len(packets)))
        assert b"".join(base64.b64decode(p["audio"]) for p in packets) == expected
        assert all(len(base64.b64decode(p["audio"])) <= 48 * 1024 for p in packets)
        assert not any(p["is_final_package"] for p in packets[:-1])
        assert packets[-1]["is_final_package"] and not packets[-1]["audio_error"]
        assert [p["expression"] for p in packets if p["expression"]] == ["moemoe"]
        ephemeral = delivery is d.OutputDelivery.EPHEMERAL_REACTION
        assert all(p["is_ephemeral"] is ephemeral and p["display_in_chat"] is not ephemeral for p in packets)
        assert [p["text"] for p in packets if p["text"]] == ([] if ephemeral else ["你好"])
        assert calls == ([] if prepared else ["你好"])
    finally:
        await adapter.disconnect(stage)


@pytest.mark.asyncio
async def test_whole_messages_are_ordered_and_other_connection_is_independent():
    socket, connection, adapter, stage = await setup_output()
    other = Endpoint("other", character_id="miku")
    await adapter.bind(other, connection)
    socket.gate = asyncio.Event()
    first = adapter.submit_output(output())
    await socket.entered.wait()
    tail = adapter.submit_output(end())
    second = adapter.submit_output(output(interaction_id="other", text="second"))
    last = adapter.submit_output(end(interaction_id="other"))
    independent, _, _, third = await setup_output(adapter, "third", "another")
    await adapter.submit_output(output(interaction_id="third"))
    await adapter.submit_output(end(interaction_id="third"))
    assert independent.events and not first.done() and not second.done()
    socket.gate.set()
    await asyncio.gather(first, tail, second, last)
    assert [p["payload"]["is_final_package"] for p in socket.events] == [False, True, False, True]
    for item in (stage, other, third):
        await adapter.disconnect(item)


@pytest.mark.asyncio
async def test_cancel_marks_before_return_and_ends_inflight_before_next_message():
    socket, connection, adapter, stage = await setup_output()
    socket.gate = asyncio.Event()
    first = adapter.submit_output(output(d.AudioChunkOutput, data=b"x" * 100000, framing=d.AudioFraming.COMPLETE_FILE))
    tail = adapter.submit_output(end())
    await socket.entered.wait()
    cancelled = adapter.submit_output(CancelDelivery(interaction_id="interaction", execution_id="execution"))
    assert first.cancelled() and tail.cancelled()
    following = adapter.submit_output(output(execution_id="next"))
    last = adapter.submit_output(end(execution_id="next"))
    assert not cancelled.done()
    socket.gate.set()
    await asyncio.gather(cancelled, following, last)
    packets = [p["payload"] for p in socket.events]
    assert len(packets) == 4
    assert len(base64.b64decode(packets[0]["audio"])) == 48 * 1024
    assert packets[1]["is_final_package"] and packets[1]["error_code"] == "TTS_CANCELLED"
    assert packets[1]["text"] == packets[1]["audio"] == packets[1]["expression"] == ""
    assert packets[2]["uuid"] != packets[1]["uuid"]
    await adapter.disconnect(stage)


@pytest.mark.asyncio
async def test_unstarted_cancel_releases_capacity_without_packets():
    socket, _, adapter, stage = await setup_output(WebSocketAdapter({"max_outputs": 1}))
    first = adapter.submit_output(output())
    with pytest.raises(d.SinkRejectedError) as rejected:
        adapter.submit_output(end())
    assert rejected.value.code is d.SinkRejectionCode.BACKPRESSURE_TIMEOUT
    await adapter.submit_output(CancelDelivery(interaction_id="interaction", execution_id="execution"))
    assert first.cancelled() and not socket.events
    await adapter.submit_output(output(execution_id="next"))
    await adapter.submit_output(end(execution_id="next"))
    await adapter.disconnect(stage)


@pytest.mark.asyncio
async def test_disconnect_rebind_and_late_old_disconnect():
    socket, old, adapter, stage = await setup_output()
    first = adapter.submit_output(output())
    old.mark_disconnected()
    await adapter.disconnect(stage, old)
    with pytest.raises(ConnectionError):
        await first
    new_socket = Socket()
    new = WebSocketConnection(new_socket, "user", "用户")
    await adapter.bind(stage, new)
    await adapter.disconnect(stage, old)
    await adapter.submit_output(output(execution_id="new"))
    await adapter.submit_output(end(execution_id="new"))
    assert len(new_socket.events) == 2
    assert stage.states == [d.ConnectionState.CONNECTED, d.ConnectionState.DISCONNECTED, d.ConnectionState.CONNECTED]
    await adapter.disconnect(stage)


@pytest.mark.asyncio
async def test_network_failure_fails_all_futures_without_retry():
    socket, _, adapter, stage = await setup_output()
    socket.fail = True
    results = [adapter.submit_output(output()), adapter.submit_output(end())]
    assert all(isinstance(result, ConnectionError) for result in await asyncio.gather(*results, return_exceptions=True))
    with pytest.raises(d.SinkRejectedError):
        adapter.submit_output(output(execution_id="new"))
    await adapter.disconnect(stage)


@pytest.mark.asyncio
async def test_disconnect_waits_for_inflight_send_and_settles_futures():
    socket, connection, adapter, stage = await setup_output()
    socket.gate = asyncio.Event()
    future = adapter.submit_output(output())
    await socket.entered.wait()
    connection.mark_disconnected()
    closing = asyncio.create_task(adapter.disconnect(stage, connection))
    with pytest.raises(ConnectionError):
        await asyncio.wait_for(asyncio.shield(future), 1)
    assert not closing.done()
    socket.gate.set()
    await closing
    assert isinstance(future.exception(), ConnectionError)


@pytest.mark.asyncio
async def test_cancelling_disconnect_caller_still_finishes_binding_cleanup():
    socket, connection, adapter, stage = await setup_output()
    socket.gate = asyncio.Event()
    future = adapter.submit_output(output())
    await socket.entered.wait()
    closing = asyncio.create_task(adapter.disconnect(stage, connection))
    # 等待解除操作真正开始，再取消调用者。
    async def disconnected():
        while stage.states[-1] is not d.ConnectionState.DISCONNECTED:
            await asyncio.sleep(0)
    await asyncio.wait_for(disconnected(), 1)
    closing.cancel()
    socket.gate.set()
    with pytest.raises(asyncio.CancelledError):
        await closing
    assert future.cancelled()
    with pytest.raises(d.SinkRejectedError):
        adapter.submit_output(end())
    await adapter.bind(stage, WebSocketConnection(Socket(), "user", "用户"))
    await adapter.submit_output(end(execution_id="new"))
    await adapter.disconnect(stage)


@pytest.mark.asyncio
async def test_input_targets_are_atomic_and_use_authenticated_identity():
    _, connection, adapter, stage = await setup_output()
    other = Endpoint("other", character_id="miku")
    await adapter.bind(other, connection)
    event = WSMessage(event_type="user_text", client_msg_id="one", payload={"text": "你好",
                      "target_character_ids": ["luotianyi", "miku"], "user_id": "forged"})
    other.available = False
    assert not adapter.receive_event(connection, event)
    assert not stage.stimuli and not other.stimuli
    other.available = True
    assert adapter.receive_event(connection, event)
    assert stage.stimuli[0] is other.stimuli[0]
    assert stage.stimuli[0].user_id == "user"
    assert stage.stimuli[0].occurred_at.tzinfo is not None
    with pytest.raises(ValueError):
        adapter.receive_event(connection, WSMessage(event_type="user_text", client_msg_id="bad", payload={"text": "hi", "target_character_ids": ["missing"]}))
    for endpoint in (stage, other):
        await adapter.disconnect(endpoint)


@pytest.mark.asyncio
async def test_service_dedup_overload_typing_and_maintenance_bypass():
    _, connection, adapter, stage = await setup_output()
    service = WebSocketService()
    event = WSMessage(event_type="user_typing", client_msg_id="typing", payload={"text_length": 4})
    stage.available = False
    assert service.try_accept_stimulus_event(connection, event, adapter=adapter) is ChatEventAcceptance.OVERLOADED
    stage.available = True
    assert service.try_accept_stimulus_event(connection, event, adapter=adapter) is ChatEventAcceptance.ACCEPTED
    assert service.try_accept_stimulus_event(connection, event, adapter=adapter) is ChatEventAcceptance.DUPLICATE
    assert len(stage.stimuli) == 1 and isinstance(stage.stimuli[0], d.UserTyping)
    assert stage.stimuli[0].text_length == 4
    bad = WSMessage(event_type="user_typing", client_msg_id="bad", payload={"text_length": True})
    assert service.try_accept_stimulus_event(connection, bad, adapter=adapter) is ChatEventAcceptance.BAD_MESSAGE
    assert service.try_accept_stimulus_event(connection, WSMessage(event_type="heartbeat", payload={}), adapter=object()) is ChatEventAcceptance.UNSUPPORTED
    await adapter.disconnect(stage)


@pytest.mark.parametrize("status,code,expected", [
    (d.MessageEndStatus.COMPLETED, None, None),
    (d.MessageEndStatus.CANCELLED, None, "TTS_CANCELLED"),
    (d.MessageEndStatus.FAILED, d.AudioErrorCode.EMPTY_AUDIO, "TTS_EMPTY"),
    (d.MessageEndStatus.FAILED, d.AudioErrorCode.GENERATION_FAILED, "TTS_STREAM_ERROR"),
])
@pytest.mark.asyncio
async def test_terminal_mapping(status, code, expected):
    socket, _, adapter, stage = await setup_output()
    await adapter.submit_output(output(d.MessageEndOutput, status=status, error_code=code))
    assert socket.events[0]["payload"]["error_code"] == expected
    await adapter.disconnect(stage)


@pytest.mark.asyncio
async def test_foreign_binding_rejected_and_state_signal_supported():
    socket, _, adapter, stage = await setup_output()
    with pytest.raises(ValueError):
        await adapter.bind(stage, WebSocketConnection(Socket(), "other", "其他人"))
    await adapter.submit_output(AgentPresentationChanged(interaction_id="interaction", state=AgentPresentationState.THINKING))
    assert socket.events[0]["payload"] == {"state": "thinking"}
    await adapter.disconnect(stage)


@pytest.mark.parametrize("config", [[], {"max_outputs": 0}, {"max_bytes": True}, {"max_messages": -1}])
def test_invalid_config(config):
    with pytest.raises((TypeError, ValueError)):
        WebSocketAdapter(config)


def test_real_fastapi_websocket_prepared_say(tmp_path):
    app = FastAPI()
    agent, plan, expected, _ = agent_and_plan(tmp_path, prepared=True, delivery=d.OutputDelivery.CONVERSATION)
    @app.websocket("/test")
    async def endpoint(websocket: WebSocket):
        await websocket.accept()
        connection = WebSocketConnection(websocket, "user", "用户")
        adapter, stage = WebSocketAdapter(), Endpoint()
        await adapter.bind(stage, connection)
        try:
            event = WSMessage(**await websocket.receive_json())
            assert adapter.receive_event(connection, event)
            assert stage.stimuli[0].text == "你好"
            port = OutputPort(adapter)
            context = d.ExecutionContext(execution_id="execution", interaction_id="interaction",
                current_interaction_revision=1, cancellation=d.CancellationToken())
            await agent.realize_action_plan(plan, context, port)
            await asyncio.gather(*port.futures)
        finally:
            await adapter.disconnect(stage)
            await websocket.close()
    with TestClient(app) as client, client.websocket_connect("/test") as websocket:
        websocket.send_json({"event_type": "user_text", "client_msg_id": "one", "payload": {"text": "你好"}})
        packets = []
        while not packets or not packets[-1]["is_final_package"]:
            packets.append(websocket.receive_json()["payload"])
        assert b"".join(base64.b64decode(packet["audio"]) for packet in packets) == expected
