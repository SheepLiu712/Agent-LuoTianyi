"""首音频经过真实 Session / Binding / Web 发送完成边界才统计。"""

import asyncio
from dataclasses import replace

import pytest

from src.adapter.websocket.call_v1 import CallWebSocketAdapter
from src.adapter.websocket.call_v1._binding import Binding
from src.adapter.websocket.call_v1._session import Session
from src.adapter.websocket.connection import AdapterConnection
from src.infrastructure.observability.call_metrics import CallMetricName
from src.stage.call_stage import CallPCM, CallStage
from src.web.websocket._adapter_io import _send_pump
from tests.integration.stage import test_call_stage as b
from tests.integration.stage import test_call_stage_review as r

call_setup = b.call_setup


@pytest.fixture
async def network_call(call_setup):
    repository, record, ownership, clock = call_setup
    captured = []

    class Metrics:
        def record(self, metric):
            captured.append(metric)
            return True

    handler = b._TurnHandler()
    handler.gate.set()
    adapter = CallWebSocketAdapter(manager=None)
    stage = CallStage(
        ownership=ownership,
        record=record,
        agent=b._agent(handler),
        context_factory=b.ContextFactory(character_id="luotianyi", database=b._ContextDatabase()),
        call_sessions=repository,
        speech_factory=b.FakeRealtimeSpeechSessionFactory(),
        output_sink=adapter.submit_output,
        call_metrics=Metrics(),
        monotonic=clock.tick,
        wall_clock=clock.now,
    )
    session = Session(stage)
    handle = AdapterConnection()
    binding = Binding(session, connection_id=object())
    await session.attach(binding)
    binding.is_ready = True
    adapter._sessions[stage.call_id] = session
    adapter._bindings[handle] = binding
    await stage.start()
    await stage.apply_answer(
        b.d.AnswerCall(action_id="answer", call_id=record.call_id, decision=b.CallAnswerDecision.ACCEPT)
    )
    await b._eventually(lambda: stage.state is b.CallState.ACTIVE)
    stage._agent._action_router = b.ActionRouter(((b.d.ActionKind.SAY, r._TimedMultiChunkSay(clock, (0.125, 0.250))),))
    try:
        yield stage, adapter, handle, binding, clock, captured
    finally:
        await stage.terminate(b.CallEndReason.USER_HANGUP)
        await session.close()


def first_audio(captured):
    return [m.duration_ms for m in captured if m.name is CallMetricName.FIRST_AUDIO]


async def produce_turn(stage):
    await stage._provider.emit(b.TurnCompleted(b.CallAudioSemantic(transcript="测试轮次")))
    await r._await_realized(stage)


async def next_audio(adapter, handle):
    while True:
        delivery = await asyncio.wait_for(adapter.next_output(handle), 1)
        if isinstance(delivery.message, bytes):
            return delivery
        adapter.complete_output(handle, delivery.delivery_id)


class Socket:
    def __init__(self, *, fail=False):
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.fail = fail

    async def send_text(self, _text):
        pass

    async def send_bytes(self, _data):
        self.started.set()
        await self.release.wait()
        if self.fail:
            raise ConnectionError("socket write failed")


@pytest.mark.asyncio
@pytest.mark.parametrize("result", ["success", "error", "cancel"])
async def test_first_audio_waits_for_actual_websocket_completion(network_call, result):
    stage, adapter, handle, binding, clock, captured = network_call
    await produce_turn(stage)
    assert first_audio(captured) == []  # 队列接纳没有成功样本。
    clock.advance(0.5)
    socket = Socket(fail=result == "error")
    pump = asyncio.create_task(_send_pump(socket, adapter, handle))
    try:
        await asyncio.wait_for(socket.started.wait(), 1)
        assert first_audio(captured) == []  # 已取出、正在发送仍没有成功样本。
        clock.advance(0.25)
        if result == "cancel":
            pump.cancel()
        else:
            socket.release.set()
        if result == "success":
            await b._eventually(lambda: bool(first_audio(captured)))
            assert first_audio(captured) == [875.0]
            await produce_turn(stage)
            await b._eventually(lambda: len(first_audio(captured)) == 2)
            assert first_audio(captured) == [875.0, 250.0]
        else:
            with pytest.raises(asyncio.CancelledError if result == "cancel" else ConnectionError):
                await pump
            assert binding.is_closed
            assert first_audio(captured) == []
    finally:
        binding.invalidate()
        pump.cancel()
        await asyncio.wait_for(asyncio.gather(pump, return_exceptions=True), 2)


@pytest.mark.asyncio
async def test_duplicate_completion_and_replay_do_not_add_samples(network_call):
    stage, adapter, handle, binding, clock, captured = network_call
    await produce_turn(stage)
    first = await next_audio(adapter, handle)
    adapter.complete_output(handle, first.delivery_id)
    clock.advance(0.5)
    adapter.complete_output(handle, first.delivery_id)
    tail = await next_audio(adapter, handle)
    adapter.complete_output(handle, tail.delivery_id)
    # 实际 replay 元数据仍经过新的网络投递身份；Stage 按轮去重。
    for output in binding.session._delivery.replay_after(0):
        binding.session._enqueue(binding, output)
    replay = await next_audio(adapter, handle)
    adapter.complete_output(handle, replay.delivery_id)
    assert first_audio(captured) == [125.0]


@pytest.mark.asyncio
@pytest.mark.parametrize("late_state", ["interrupted", "disconnected", "ending"])
async def test_late_network_success_does_not_record_retired_audio(network_call, late_state):
    stage, adapter, handle, binding, clock, captured = network_call
    await produce_turn(stage)
    first = await next_audio(adapter, handle)
    if late_state == "interrupted":
        stage._interrupt()
    elif late_state == "disconnected":
        await adapter.disconnect(handle)
        # 同一个 session 上新连接的投递不能由旧连接回执完成。
        new = AdapterConnection()
        replacement = Binding(binding.session, connection_id=object())
        await binding.session.attach(replacement, resume_cursor=0)
        adapter._bindings[new] = replacement
        replay = await next_audio(adapter, new)
        adapter.complete_output(handle, replay.delivery_id)
        assert replay.delivery_id in replacement._outbox._pending
        adapter.complete_output(new, replay.delivery_id)
    else:
        await stage.terminate(b.CallEndReason.USER_HANGUP)
    adapter.complete_output(handle, first.delivery_id)
    assert first_audio(captured) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("empty", [False, True])
async def test_provisional_audio_counts_but_empty_pcm_does_not(network_call, empty):
    stage, adapter, handle, binding, clock, captured = network_call
    action = r._BlockedAudioSay()
    stage._agent._action_router = b.ActionRouter(((b.d.ActionKind.SAY, action),))
    await stage._provider.emit(b.TurnCompleted(b.CallAudioSemantic(transcript="过渡语")))
    await asyncio.wait_for(action.started.wait(), 1)
    response_id = next(iter(stage._responses))
    stage._responses[response_id].provisional = True
    # 空 PCM 被协议层拒绝；有效 provisional 输出仍可作为该轮首包。
    original = stage._output_sink

    async def send(call_id, output):
        if empty and isinstance(output, CallPCM):
            output = replace(output, payload=b"")
        await original(call_id, output)

    stage._output_sink = send
    clock.advance(0.125)
    action.release.set()
    await r._await_realized(stage)
    if empty:
        assert first_audio(captured) == []
        return
    audio = await next_audio(adapter, handle)
    adapter.complete_output(handle, audio.delivery_id)
    assert first_audio(captured) == [125.0]
