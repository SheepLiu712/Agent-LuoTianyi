import asyncio
from types import SimpleNamespace

import pytest

import src.domain.agent as d
from src.agent.handlers.action.say import SayHandler
from src.agent.processing.execution import Execution
from src.domain.call import CallAudioRoute, CallSpeechDelivery


class Permit:
    def __init__(self, allowed=True):
        self.allowed = allowed

    def allows(self, response_id):
        assert response_id == "response"
        return self.allowed


class Speaking:
    def __init__(self, permit, chunks=(b"one!", b"two!"), block_before_second=None):
        self.permit = permit
        self.chunks = chunks
        self.block_before_second = block_before_second
        self.started = 0
        self.pulls = 0
        self.closed = False

    async def speak(self, invocation, *, text, tone, output_format=None):
        del invocation, text, tone
        assert output_format == d.CALL_PCM_FORMAT
        self.started += 1
        try:
            for index, chunk in enumerate(self.chunks):
                if index == 1 and self.block_before_second is not None:
                    await self.block_before_second.wait()
                self.pulls += 1
                yield SimpleNamespace(data=chunk, framing=d.AudioFraming.RAW_PCM, audio_format=output_format)
                if index == 0:
                    await asyncio.sleep(0)
        finally:
            self.closed = True


class RealSpeakingEngine:
    def __init__(self, worker_clips):
        self.worker_clips = worker_clips
        self.pulls = 0
        self.closed = False

    async def stream(self, **_kwargs):
        try:
            for clip in self.worker_clips:
                self.pulls += 1
                yield clip
        finally:
            self.closed = True


class Sink:
    def __init__(self, permit, revoke_on_audio=False, block_audio=None):
        self.permit = permit
        self.revoke_on_audio = revoke_on_audio
        self.block_audio = block_audio
        self.outputs = []

    async def emit(self, output):
        self.outputs.append(output)
        if self.block_audio is not None and isinstance(output, d.AudioChunkOutput):
            await self.block_audio.wait()
        if self.revoke_on_audio and isinstance(output, d.AudioChunkOutput):
            self.permit.allowed = False
        return d.OutputReceipt(
            execution_id=output.execution_id,
            sequence_no=output.sequence_no,
            status=d.OutputAcceptanceStatus.ACCEPTED,
        )


def _execution(speaking, permit, sink):
    action = d.Say(
        action_id="say",
        content="正式文本",
        sound_content="正式文本",
        prepared_audio_ref=None,
        tone=d.Tone(value="normal"),
        expression=None,
        delivery=d.OutputDelivery.EPHEMERAL_REACTION,
        call_delivery=CallSpeechDelivery(
            audio_route=CallAudioRoute.CALL,
            display_in_chat=False,
            is_ephemeral=True,
            provisional=True,
            response_id="response",
        ),
    )
    plan = d.ActionPlan(
        plan_id="plan",
        origin_request_id="request",
        plan_ordinal=0,
        target_character_id="luotianyi",
        interaction_id="call",
        basis_interaction_revision=0,
        source_stimulus_ids=("stimulus",),
        actions=(action,),
    )
    context = d.ExecutionContext(
        execution_id="execution",
        interaction_id="call",
        current_interaction_revision=0,
        cancellation=d.CancellationToken(),
        call_output_permit=permit,
    )
    handler = SayHandler("luotianyi", speaking, SimpleNamespace())
    agent = SimpleNamespace(
        _action_router=SimpleNamespace(resolve=lambda _kind: handler),
        _error_code=lambda error, enum: (
            enum.CANCELLED if isinstance(error, d.SinkRejectedError) else enum.INTERNAL_ERROR
        ),
        _record_exception=lambda *args: None,
        _action_result=lambda item: d.ActionResult(
            action_id=item.action_id,
            status=d.ActionExecutionStatus.FAILED,
            error_code=d.ExecutionErrorCode.INTERNAL_ERROR,
            irreversible_effect_committed=False,
            effect_ref=None,
        ),
        _execution_report=lambda *args: d.ExecutionReport(
            plan_id=plan.plan_id,
            execution_id=context.execution_id,
            status=args[2],
            error_code=args[3],
            action_results=tuple(args[4]),
            output_started=args[5],
            retryable=args[6],
        ),
    )
    return Execution(agent, plan, context, sink)


@pytest.mark.asyncio
async def test_missing_or_denied_permit_fails_before_tts():
    for permit in (None, Permit(False)):
        speaking = Speaking(permit)
        sink = Sink(permit)
        report = await _execution(speaking, permit, sink).run()
        assert report.status is d.ExecutionStatus.CANCELLED
        assert speaking.started == 0
        assert sink.outputs == []


@pytest.mark.asyncio
async def test_revocation_drops_pending_final_and_success_end_and_closes_stream():
    permit = Permit()
    speaking = Speaking(permit, chunks=(b"one!", b"two!", b"late"))
    sink = Sink(permit, revoke_on_audio=True)

    report = await _execution(speaking, permit, sink).run()

    assert report.status is d.ExecutionStatus.CANCELLED
    assert speaking.closed
    audio = [output for output in sink.outputs if isinstance(output, d.AudioChunkOutput)]
    assert [output.data for output in audio] == [b"one!"]
    assert all(not output.final for output in audio)
    assert not any(isinstance(output, d.MessageEndOutput) for output in sink.outputs)


@pytest.mark.asyncio
async def test_blocked_sink_applies_backpressure_without_extra_tts_pulls():
    permit = Permit()
    release_sink = asyncio.Event()
    speaking = Speaking(permit, chunks=(b"one!", b"two!", b"three!"))
    sink = Sink(permit, block_audio=release_sink)

    task = asyncio.create_task(_execution(speaking, permit, sink).run())
    for _ in range(20):
        if any(isinstance(output, d.AudioChunkOutput) for output in sink.outputs):
            break
        await asyncio.sleep(0)
    assert speaking.pulls == 2
    await asyncio.sleep(0.01)
    assert speaking.pulls == 2

    release_sink.set()
    report = await task
    assert report.status is d.ExecutionStatus.COMPLETED
    assert speaking.pulls == 3
    audio = [output for output in sink.outputs if isinstance(output, d.AudioChunkOutput)]
    assert [output.final for output in audio] == [False, False, True]
    assert isinstance(sink.outputs[-1], d.MessageEndOutput)


@pytest.mark.asyncio
async def test_large_worker_clip_is_bounded_and_only_last_subchunk_is_final():
    from src.agent.skills.expression.speaking import SpeakingSkill

    permit = Permit()
    clip = b"\x01\x00" * 16384  # 32768 bytes -> two protocol-sized chunks
    engine = RealSpeakingEngine((clip,))
    speaking = SpeakingSkill({}, engine)
    sink = Sink(permit)

    report = await _execution(speaking, permit, sink).run()

    assert report.status is d.ExecutionStatus.COMPLETED
    audio = [output for output in sink.outputs if isinstance(output, d.AudioChunkOutput)]
    assert [len(output.data) for output in audio] == [16384, 16384]
    assert [output.final for output in audio] == [False, True]
    assert b"".join(output.data for output in audio) == clip
    assert engine.pulls == 1
    assert engine.closed
