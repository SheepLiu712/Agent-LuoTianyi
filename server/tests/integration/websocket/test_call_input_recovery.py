"""从真实通话连接观察队列恢复后的接纳、累计确认和缺帧请求。"""

import asyncio
import json
from types import SimpleNamespace

import pytest
import pytest_asyncio
from support.call_session_repository import InMemoryCallSessionRepository
from support.realtime_speech import FakeRealtimeSpeechSession, FakeRealtimeSpeechSessionFactory
from support.stage_manager import make_call_adapter, make_stage_manager
from support.stage_support import RecordingAgent, report

import src.domain.agent as d
from src.adapter.websocket.call_v1._audio_codec import BinaryAudioFrameCodec, WireAudioFrame
from src.adapter.websocket.chat import WebSocketAdapter
from src.agent.context import ContextFactory
from src.application.user.reset_fence import UserResetFence
from src.domain.call import CallAnswerDecision, CallEndingResult, CallState, CallSummarySource
from src.domain.stage.lifecycle import StageEndReason


class _ContextDatabase:
    def get_user_description(self, _user_id):
        return ""

    def get_user_preferences(self, _user_id):
        return {}

    def get_call_conversation_seed_state(self, _user_id, **_kwargs):
        return {"summary": "", "conversations": []}


class _CallAgent(RecordingAgent):
    async def handle_stimulus(self, request, sink, *, context=None):
        if not isinstance(request.stimulus, d.CallEnding):
            return await super().handle_stimulus(request, sink, context=context)
        plan = d.ActionPlan(
            plan_id="ending-plan",
            origin_request_id=request.request_id,
            plan_ordinal=0,
            target_character_id="luotianyi",
            interaction_id=request.interaction.interaction_id,
            basis_interaction_revision=request.interaction.interaction_revision,
            source_stimulus_ids=(request.stimulus.stimulus_id,),
            actions=(
                d.FinalizeCall(
                    action_id="ending-action",
                    user_id="user",
                    final_snapshot=request.stimulus.final_snapshot,
                ),
            ),
        )
        await sink.emit(plan)
        return report(request, plans=(plan.plan_id,))

    async def realize_action_plan(self, value, context, sink):
        return SimpleNamespace(
            status=d.ExecutionStatus.COMPLETED,
            action_results=(SimpleNamespace(value=CallEndingResult("测试通话", CallSummarySource.DEFAULT, True, 0)),),
        )


class _ControlledSpeech(FakeRealtimeSpeechSession):
    """只控制供应商消费速度；协议、Stage 队列和容量等待均使用生产实现。"""

    def __init__(self):
        super().__init__()
        self.entered = asyncio.Queue()
        self.completed = asyncio.Queue()
        self.permits = asyncio.Queue()

    async def push_audio(self, frame):
        self.entered.put_nowait(frame.payload)
        await self.permits.get()
        await super().push_audio(frame)
        self.completed.put_nowait(frame.payload)

    async def started(self, seq):
        assert await asyncio.wait_for(self.entered.get(), 1) == _payload(seq)

    async def finish(self, seq):
        self.permits.put_nowait(None)
        assert await asyncio.wait_for(self.completed.get(), 1) == _payload(seq)


class _SpeechFactory(FakeRealtimeSpeechSessionFactory):
    async def create(self, call_id):
        self.sessions[call_id] = _ControlledSpeech()
        return self.sessions[call_id]


def _payload(seq):
    return seq.to_bytes(2, "little")


def _audio(seq):
    return BinaryAudioFrameCodec().encode(WireAudioFrame(1, 2, 0, 0, seq, _payload(seq)))


class _CallConnection:
    def __init__(self, adapter, connection, stage, speech):
        self.adapter, self.connection, self.stage, self.speech = adapter, connection, stage, speech
        self.messages = []

    async def send(self, seq):
        await self.adapter.receive(self.connection, _audio(seq))

    async def until(self, predicate):
        async def receive():
            while True:
                output = await self.adapter.next_output(self.connection)
                self.adapter.complete_output(self.connection, output.delivery_id)
                message = json.loads(output.message)
                self.messages.append(message)
                if predicate(message):
                    return message

        return await asyncio.wait_for(receive(), 1)

    async def ack(self, seq):
        return await self.until(lambda message: message["type"] == "ack" and message["ack_seq"] == seq)

    async def overloaded(self, seq):
        return await self.until(
            lambda message: message["type"] == "error"
            and message["code"] == "OVERLOADED"
            and message["request_seq"] == seq
        )

    async def fill(self):
        # 帧 2 正在写供应商，帧 3 占满唯一排队槽；之后的帧只能留在协议缓存。
        await self.send(2)
        await self.ack(2)
        await self.speech.started(2)
        await self.send(3)
        await self.ack(3)

    async def resume(self):
        self.connection = await self.adapter.open(
            initial_message=json.dumps(
                {
                    "protocol": "call.v1",
                    "type": "call.resume",
                    "call_id": self.stage.call_id,
                    "character_id": "luotianyi",
                    "last_contiguous_server_seq": 0,
                }
            ),
            user_id="user",
            connection_id=object(),
        )
        return await self.until(lambda message: message["type"] == "call.resumed")

    def assert_delivered(self, *seqs):
        assert [frame.payload for frame in self.speech.pushed_frames] == [_payload(seq) for seq in seqs]


@pytest_asyncio.fixture
async def call():
    speech = _SpeechFactory()
    stages = make_stage_manager(
        get_agent=lambda _character: _CallAgent(),
        adapter=WebSocketAdapter(),
        get_context_factory=lambda _character: ContextFactory(character_id="luotianyi", database=_ContextDatabase()),
        call_sessions=InMemoryCallSessionRepository(),
        realtime_speech_factory=speech,
        user_reset_fence=UserResetFence(),
        config={"call_stage": {"pcm_queue_capacity": 1}},
    )
    adapter = make_call_adapter(
        manager=stages,
        user_reset_fence=stages._user_reset_fence,
        enabled=True,
        supports_character=lambda _character: True,
    )
    try:
        connection = await adapter.open(
            initial_message=json.dumps(
                {
                    "protocol": "call.v1",
                    "type": "call.start",
                    "seq": 1,
                    "client_request_id": "input-recovery",
                    "character_id": "luotianyi",
                    "audio": {"encoding": "pcm_s16le", "sample_rate": 16000, "channels": 1},
                }
            ),
            user_id="user",
            connection_id=object(),
        )
        preparing = await adapter.next_output(connection)
        adapter.complete_output(connection, preparing.delivery_id)
        call_id = json.loads(preparing.message)["call_id"]
        stage = stages._call_stages[call_id]
        probe = _CallConnection(adapter, connection, stage, None)
        await probe.ack(1)

        async def answer():
            while stage.state is not CallState.RINGING:
                await asyncio.sleep(0)
            await stage.apply_answer(
                d.AnswerCall(action_id="answer", call_id=stage._record.call_id, decision=CallAnswerDecision.ACCEPT)
            )

        await asyncio.wait_for(answer(), 1)
        probe.speech = speech.sessions[stage._record.call_id]
        await probe.until(lambda message: message["type"] == "call.active")
        yield probe
    finally:
        await asyncio.wait_for(adapter.close(), 3)
        await asyncio.wait_for(stages.close(), 3)


@pytest.mark.asyncio
async def test_partial_capacity_acknowledges_accepted_audio_before_next_frame_fits(call):
    await call.fill()
    await call.send(4)
    await call.overloaded(4)
    await call.send(5)
    await call.overloaded(4)
    assert not any(message["type"] == "nack" for message in call.messages)

    await call.speech.finish(2)
    await call.speech.started(3)
    await call.ack(4)
    await call.speech.finish(3)
    await call.speech.started(4)
    await call.ack(5)
    await call.speech.finish(4)
    await call.speech.started(5)
    await call.speech.finish(5)
    call.assert_delivered(2, 3, 4, 5)


@pytest.mark.asyncio
async def test_capacity_recovery_requests_a_real_gap_and_accepts_replay_once(call):
    await call.fill()
    await call.send(4)
    await call.overloaded(4)
    await call.send(6)
    await call.overloaded(4)
    assert not any(message["type"] == "nack" for message in call.messages)

    await call.speech.finish(2)
    await call.speech.started(3)
    await call.ack(4)
    await call.until(lambda message: message["type"] == "nack" and message["missing_seq"] == 5)
    await call.send(5)
    await call.overloaded(5)
    await call.speech.finish(3)
    await call.speech.started(4)
    await call.ack(5)
    await call.speech.finish(4)
    await call.speech.started(5)
    await call.ack(6)
    await call.speech.finish(5)
    await call.speech.started(6)
    await call.speech.finish(6)
    call.assert_delivered(2, 3, 4, 5, 6)


@pytest.mark.asyncio
async def test_capacity_stolen_by_foreground_does_not_abandon_next_capacity_release(call, monkeypatch):
    capacity_seen, continue_background = asyncio.Event(), asyncio.Event()
    wait_capacity = call.stage.wait_pcm_capacity

    async def hold_awakened_background():
        await wait_capacity()
        capacity_seen.set()
        await continue_background.wait()

    monkeypatch.setattr(call.stage, "wait_pcm_capacity", hold_awakened_background)
    await call.fill()
    await call.send(4)
    await call.overloaded(4)
    await call.speech.finish(2)
    await call.speech.started(3)
    await asyncio.wait_for(capacity_seen.wait(), 1)
    try:
        # 前台先取得唯一空位，旧后台仍在运行，不能靠新建任务补救这一次竞争。
        await call.send(5)
        await call.overloaded(5)
        continue_background.set()
        await call.overloaded(5)
        await call.speech.finish(3)
        await call.speech.started(4)
        await call.ack(5)
        await call.speech.finish(4)
        await call.speech.started(5)
        await call.speech.finish(5)
        call.assert_delivered(2, 3, 4, 5)
    finally:
        continue_background.set()


@pytest.mark.asyncio
async def test_available_capacity_before_resume_still_drains_without_new_uplink(call, monkeypatch):
    rejected_offline = asyncio.Event()
    accept_pcm = call.stage.accept_pcm
    offline_rejections = 0

    def observe_lifecycle_rejection(receipt, payload):
        nonlocal offline_rejections
        accepted = accept_pcm(receipt, payload)
        if not accepted and call.stage.state is CallState.RECONNECTING:
            offline_rejections += 1
            rejected_offline.set()
        return accepted

    monkeypatch.setattr(call.stage, "accept_pcm", observe_lifecycle_rejection)
    await call.fill()
    await call.send(4)
    await call.overloaded(4)
    await call.adapter.disconnect(call.connection)
    await call.speech.finish(2)
    await call.speech.started(3)
    await asyncio.wait_for(rejected_offline.wait(), 1)
    for _ in range(20):
        await asyncio.sleep(0)
    assert offline_rejections == 1, "非 ACTIVE 拒绝不能在空队列上持续重试"
    await call.resume()
    await call.ack(4)
    await call.speech.finish(3)
    await call.speech.started(4)
    await call.speech.finish(4)
    call.assert_delivered(2, 3, 4)


@pytest.mark.asyncio
async def test_termination_while_capacity_waits_closes_without_accepting_cached_audio(call):
    await call.fill()
    await call.send(4)
    await call.overloaded(4)
    ending = asyncio.create_task(call.stage.terminate(StageEndReason.USER_REQUESTED))
    await call.until(lambda message: message["type"] == "call.ended")
    result = await asyncio.wait_for(ending, 2)
    assert result.resources_released and result.cleanup_error is None and result.finalization_error is None
    assert call.speech.closed
    assert _payload(4) not in [frame.payload for frame in call.speech.pushed_frames]
