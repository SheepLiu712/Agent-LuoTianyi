"""Persistent evidence for unified CallStage transport-abort behavior."""

import asyncio
import json

import pytest
from support.call_stage_failure_harness import activate, create_active_stage, eventually

from src.domain.call import CallAudioSemantic, CallEndReason, CallOutcome, CallState
from src.infrastructure.models.realtime_speech import SpeechStarted, TurnCompleted


async def assert_terminal(stage, repository, record, ownership, provider, transport, settlement, released):
    assert stage._transport_abort_task is not None
    await asyncio.shield(stage._transport_abort_task)
    await asyncio.sleep(0)
    snapshot = stage.snapshot
    assert snapshot.terminal.outcome is CallOutcome.CONNECTED
    assert snapshot.terminal.end_reason is CallEndReason.SYSTEM_FAILURE
    assert repository.find_by_id(record.call_id).state is CallState.ENDED
    assert released == [ownership]
    assert provider.closed is True
    assert stage.context is None
    assert settlement.snapshots == [snapshot]
    assert transport.count("ended") == 1
    assert stage._closed.is_set()
    assert not stage.tasks
    assert stage._transport_abort_task.done()
    assert stage._transport_abort_task.exception() is None


@pytest.mark.asyncio
async def test_active_state_delivery_failure_uses_one_owned_abort(tmp_path):
    values = await create_active_stage(tmp_path)
    stage, repository, record, ownership, provider, transport, settlement, released = values
    transport.fail = {"state_active"}

    with pytest.raises(RuntimeError, match="state_active failed"):
        await activate(stage, record.call_id)
    await eventually(lambda: stage.snapshot is not None)
    await stage.wait_closed()

    await assert_terminal(stage, repository, record, ownership, provider, transport, settlement, released)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["start_stream", "send_pcm"])
async def test_response_delivery_failure_uses_one_owned_abort(tmp_path, operation):
    values = await create_active_stage(tmp_path)
    stage, repository, record, ownership, provider, transport, settlement, released = values
    await activate(stage, record.call_id)
    transport.fail = {operation}

    await provider.emit(TurnCompleted(CallAudioSemantic(transcript="你好")))
    await eventually(lambda: stage.snapshot is not None)
    await stage.wait_closed()

    await assert_terminal(stage, repository, record, ownership, provider, transport, settlement, released)


@pytest.mark.asyncio
async def test_stop_delivery_failure_uses_one_owned_abort(tmp_path):
    values = await create_active_stage(tmp_path)
    stage, repository, record, ownership, provider, transport, settlement, released = values
    await activate(stage, record.call_id)
    await provider.emit(TurnCompleted(CallAudioSemantic(transcript="你好")))
    await eventually(lambda: bool(stage._playback.pending_streams))
    transport.fail = {"stop_response"}

    await provider.emit(SpeechStarted())
    await eventually(lambda: stage.snapshot is not None)
    await stage.wait_closed()

    await assert_terminal(stage, repository, record, ownership, provider, transport, settlement, released)


@pytest.mark.asyncio
async def test_two_concurrent_stop_failures_collapse_to_one_abort(tmp_path):
    values = await create_active_stage(tmp_path, response_count=2)
    stage, repository, record, ownership, provider, transport, settlement, released = values
    await activate(stage, record.call_id)
    await provider.emit(TurnCompleted(CallAudioSemantic(transcript="你好")))
    await eventually(lambda: len(stage._playback.pending_streams) == 2)
    transport.fail = {"stop_response"}

    await provider.emit(SpeechStarted())
    await eventually(lambda: stage.snapshot is not None)
    await stage.wait_closed()
    await asyncio.sleep(0)

    await assert_terminal(stage, repository, record, ownership, provider, transport, settlement, released)


@pytest.mark.asyncio
async def test_user_interrupt_during_real_audio_backpressure_keeps_call_active(tmp_path):
    from src.adapter.websocket.call_v1 import CallStageBinding, CallTransportSession, WireAudioFrame

    stage, repository, record, _, provider, _, settlement, _ = await create_active_stage(tmp_path)
    stopped = asyncio.Event()
    delivered_audio = asyncio.Event()
    prefilled = False

    async def deliver(output):
        nonlocal prefilled
        if output.binary:
            delivered_audio.set()
        if output.text:
            message = json.loads(output.text)
            if message["type"] == "audio.stream_started" and not prefilled:
                prefilled = True
                for _ in range(90):
                    session.send_audio(
                        WireAudioFrame(1, 2, 0, message["stream_id"], session.next_server_seq, b"\0" * 16000)
                    )
            if message["type"] == "playback.stop":
                stopped.set()

    bridge = CallStageBinding(call_id=str(record.call_id), deliver=deliver)
    session = CallTransportSession(call_id=str(record.call_id), user_id="user", character_id="luotianyi", sink=bridge)
    bridge.bind(stage=stage, session=session)
    stage._transport = bridge
    try:
        await activate(stage, record.call_id)
        await provider.emit(TurnCompleted(CallAudioSemantic(transcript="第一轮")))
        await eventually(lambda: stage._pending_send == 1 and not session._replay_capacity_event.is_set())
        old_realization = stage._realize_task
        await provider.emit(SpeechStarted())
        await asyncio.wait_for(stopped.wait(), 2)
        await eventually(lambda: old_realization.done())
        assert stage.state is CallState.ACTIVE
        assert not provider.closed
        assert not settlement.snapshots
        assert stage._transport_abort_task is None
        await provider.emit(TurnCompleted(CallAudioSemantic(transcript="打断后的新一轮")))
        await asyncio.wait_for(delivered_audio.wait(), 2)
        assert stage.state is CallState.ACTIVE
    finally:
        await stage.terminate()
        session.close()
        repository._sql_session_factory.kw["bind"].dispose()
