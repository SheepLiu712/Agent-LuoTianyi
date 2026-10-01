"""录音与图片选择协调信号的 Stage 时间线。"""

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from support.stage_support import RecordingAgent, cleanup, report, setup, stimulus, take

import src.domain.agent as d


def pending_ids(request):
    return tuple(item.stimulus_id for item in request.interaction.pending_stimuli)


def voice_message():
    return stimulus(
        d.VoiceMessage,
        message_uuid=str(uuid4()),
        media_ref=d.MediaRef(media_id="voice"),
        transcript=None,
        client_msg_id="voice-upload",
        duration_ms=1000,
    )


async def until(predicate):
    async def wait():
        while not predicate():
            await asyncio.sleep(0)

    await asyncio.wait_for(wait(), 2)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "coordination,expected_wait",
    [
        (lambda: stimulus(d.VoiceRecordingStarted, recording_id="recording"), 40),
        (lambda: stimulus(d.VoiceRecordingCancelled, recording_id="recording"), 1),
        (lambda: stimulus(d.VoiceRecordingCommitted, upload_id="upload"), 15),
        (lambda: stimulus(d.VoiceUploadFailed, upload_id="upload", reason="aborted"), 1),
        (lambda: stimulus(d.ImageSelectionOpened), 60),
        (lambda: stimulus(d.ImageSelectionClosed), 1),
    ],
)
async def test_coordination_sets_product_wait_only_when_pending(coordination, expected_wait):
    preprocessing_gate = asyncio.Event()

    async def handle(request, sink):
        if isinstance(request.stimulus, d.TextMessage):
            await preprocessing_gate.wait()
        return report(request)

    stage, _, adapter, _, _ = await setup(RecordingAgent(handle), {"response_wait": 1})
    try:
        before = datetime.now(timezone.utc)
        stage.stimulus_input_sink.submit(coordination())
        assert stage._wait_until is None

        stage.stimulus_input_sink.submit(stimulus())
        await until(lambda: bool(stage._pending))
        before = datetime.now(timezone.utc)
        stage.stimulus_input_sink.submit(coordination())
        assert abs((stage._wait_until - before).total_seconds() - expected_wait) < 0.1
    finally:
        preprocessing_gate.set()
        await cleanup(stage, adapter)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "coordination,expected_wait",
    [
        (lambda: stimulus(d.VoiceRecordingStarted, recording_id="recording"), 40),
        (lambda: stimulus(d.ImageSelectionOpened), 60),
    ],
)
async def test_opening_input_cancels_interruptible_reply_and_restores_pending(coordination, expected_wait):
    reply_started = asyncio.Event()
    cancelled = asyncio.Event()
    replies = asyncio.Queue()

    async def handle(request, sink):
        if isinstance(request.stimulus, d.InteractionDeadline):
            replies.put_nowait(request)
            if replies.qsize() == 1:
                reply_started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
            return report(request, consumed=pending_ids(request))
        return report(request)

    stage, _, adapter, _, _ = await setup(RecordingAgent(handle), {"response_wait": 0.01})
    text = stimulus()
    try:
        stage.stimulus_input_sink.submit(text)
        old_reply = await take(replies)
        await reply_started.wait()

        before = datetime.now(timezone.utc)
        stage.stimulus_input_sink.submit(coordination())
        await cancelled.wait()

        assert old_reply.cancellation.reason is d.CancellationReason.SUPERSEDED
        assert stage._pending[text.stimulus_id].status.value == "ready"
        assert abs((stage._wait_until - before).total_seconds() - expected_wait) < 0.1
    finally:
        await cleanup(stage, adapter)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "coordination",
    [
        lambda: stimulus(d.VoiceRecordingStarted, recording_id="recording"),
        lambda: stimulus(d.ImageSelectionOpened),
    ],
)
async def test_opening_input_keeps_non_interruptible_reply_running(coordination):
    reply_gate = asyncio.Event()
    replies = asyncio.Queue()

    async def handle(request, sink):
        if isinstance(request.stimulus, d.InteractionDeadline):
            replies.put_nowait(request)
            await reply_gate.wait()
            return report(request, consumed=pending_ids(request))
        return report(request)

    class NonInterruptibleAgent(RecordingAgent):
        def is_handle_interruptible(self, interaction_id, request_id=None):
            return False

    stage, _, adapter, _, _ = await setup(NonInterruptibleAgent(handle), {"response_wait": 0.01})
    try:
        stage.stimulus_input_sink.submit(stimulus())
        old_reply = await take(replies)
        stage.stimulus_input_sink.submit(coordination())
        await asyncio.sleep(0)

        assert not old_reply.cancellation.is_cancelled
        assert not stage._handles[old_reply.request_id].done()
    finally:
        reply_gate.set()
        await cleanup(stage, adapter)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "coordination",
    [
        lambda: stimulus(d.VoiceRecordingCancelled, recording_id="recording"),
        lambda: stimulus(d.VoiceRecordingCommitted, upload_id="upload"),
        lambda: stimulus(d.VoiceUploadFailed, upload_id="upload", reason="aborted"),
        lambda: stimulus(d.ImageSelectionClosed),
    ],
)
async def test_closing_coordination_does_not_add_reply_cancellation(coordination):
    reply_gate = asyncio.Event()
    replies = asyncio.Queue()

    async def handle(request, sink):
        if isinstance(request.stimulus, d.InteractionDeadline):
            replies.put_nowait(request)
            await reply_gate.wait()
            return report(request, consumed=pending_ids(request))
        return report(request)

    stage, _, adapter, _, _ = await setup(RecordingAgent(handle), {"response_wait": 0.01})
    try:
        stage.stimulus_input_sink.submit(stimulus())
        old_reply = await take(replies)
        stage.stimulus_input_sink.submit(coordination())
        await asyncio.sleep(0)

        assert not old_reply.cancellation.is_cancelled
        assert not stage._handles[old_reply.request_id].done()
    finally:
        reply_gate.set()
        await cleanup(stage, adapter)


@pytest.mark.asyncio
async def test_voice_preprocessing_blocks_reply_then_batches_restored_input():
    voice_gate = asyncio.Event()
    first_reply_cancelled = asyncio.Event()
    replies = asyncio.Queue()

    async def handle(request, sink):
        if isinstance(request.stimulus, d.VoiceMessage):
            await voice_gate.wait()
        if isinstance(request.stimulus, d.InteractionDeadline):
            replies.put_nowait(request)
            if replies.qsize() == 1:
                try:
                    await asyncio.Event().wait()
                finally:
                    first_reply_cancelled.set()
            return report(request, consumed=pending_ids(request))
        return report(request)

    stage, _, adapter, _, _ = await setup(RecordingAgent(handle), {"response_wait": 1})
    text = stimulus()
    voice = voice_message()
    try:
        stage.stimulus_input_sink.submit(text)
        await until(lambda: stage._deadline is not None)
        stage._on_deadline(stage._schedule_revision)
        old_reply = await take(replies)
        stage.stimulus_input_sink.submit(stimulus(d.VoiceRecordingStarted, recording_id="recording"))
        await first_reply_cancelled.wait()
        assert old_reply.cancellation.reason is d.CancellationReason.SUPERSEDED

        stage.stimulus_input_sink.submit(voice)
        await asyncio.sleep(0.04)
        assert replies.empty() and stage._deadline is None

        preprocessing_finished = datetime.now(timezone.utc)
        voice_gate.set()
        await until(lambda: stage._deadline is not None)
        assert abs((stage._deadline - preprocessing_finished).total_seconds() - 1) < 0.1
        stage._on_deadline(stage._schedule_revision)
        new_reply = await take(replies)
        assert pending_ids(new_reply) == (text.stimulus_id, voice.stimulus_id)
        assert tuple(item.stimulus_id for item in new_reply.prepared_inputs) == pending_ids(new_reply)
    finally:
        voice_gate.set()
        await cleanup(stage, adapter)
