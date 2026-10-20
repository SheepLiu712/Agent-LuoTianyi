"""Persistent evidence for unified CallStage transport-abort behavior."""

import asyncio
import json

import pytest
from support.call_output import output_sink
from support.call_stage_failure_harness import activate, create_active_stage, eventually

from src.domain.call import CallAudioSemantic, CallEndReason, CallOutcome, CallState
from src.infrastructure.models.realtime_speech import SpeechStarted, TurnCompleted


@pytest.mark.asyncio
@pytest.mark.parametrize("target", [CallState.ENDING, CallState.DECLINED, CallState.ENDED])
@pytest.mark.parametrize("cancel_owner", [False, True])
async def test_terminal_ledger_failure_closes_resources_before_signalling_completion(
    tmp_path, monkeypatch, target, cancel_owner
):
    stage, repository, record, ownership, provider, _, settlement, released = await create_active_stage(tmp_path)
    if target is not CallState.DECLINED:
        await activate(stage, record.call_id)
    context = stage.context
    original_update = repository.update_if_state
    close_entered, close_release = asyncio.Event(), asyncio.Event()
    original_close = context.close

    def fail_transition(*args, **kwargs):
        if kwargs["record"].state is target:
            raise RuntimeError("ledger unavailable")
        return original_update(*args, **kwargs)

    async def blocked_close():
        close_entered.set()
        await close_release.wait()
        await original_close()

    monkeypatch.setattr(repository, "update_if_state", fail_transition)
    monkeypatch.setattr(context, "close", blocked_close)
    reason = CallEndReason.DECLINED if target is CallState.DECLINED else CallEndReason.USER_HANGUP
    ending = stage.begin_termination(reason)
    try:
        await asyncio.wait_for(close_entered.wait(), 2)
        if cancel_owner:
            ending.cancel()
            await asyncio.sleep(0)
            await asyncio.sleep(0)
        assert not ending.done() and not stage._closed.is_set()
        assert not released
    finally:
        close_release.set()
    expected = asyncio.CancelledError if cancel_owner else RuntimeError
    with pytest.raises(expected):
        await stage.terminate()
    assert provider.closed and stage.context is None
    with pytest.raises(RuntimeError, match="交互上下文已经释放"):
        context.conversation.read_working()
    assert released == [ownership]
    assert not stage.tasks
    assert stage._closed.is_set()
    assert not settlement.snapshots
    assert await stage.wait_realtime_stopped() is None
    repository._sql_session_factory.kw["bind"].dispose()


@pytest.mark.asyncio
async def test_owner_cancellation_waits_for_provider_close_before_releasing_call(tmp_path, monkeypatch):
    stage, repository, record, ownership, provider, _, _, released = await create_active_stage(tmp_path)
    await activate(stage, record.call_id)
    context = stage.context
    entered, release = asyncio.Event(), asyncio.Event()
    original_close = provider.close

    async def blocked_close():
        entered.set()
        await release.wait()
        await original_close()

    monkeypatch.setattr(provider, "close", blocked_close)
    ending = stage.begin_termination()
    try:
        await asyncio.wait_for(entered.wait(), 2)
        ending.cancel()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not ending.done() and not stage._closed.is_set()
        assert not released and not provider.closed
        context.conversation.read_working()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await ending
    assert provider.closed and stage.context is None
    with pytest.raises(RuntimeError, match="交互上下文已经释放"):
        context.conversation.read_working()
    assert released == [ownership]
    assert not stage.tasks
    assert stage._closed.is_set()
    repository._sql_session_factory.kw["bind"].dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("target", [CallState.ENDING, CallState.DECLINED, CallState.ENDED])
async def test_terminal_state_delivery_failure_still_completes_settlement(tmp_path, monkeypatch, target):
    stage, repository, record, ownership, provider, transport, settlement, released = await create_active_stage(
        tmp_path
    )
    if target is not CallState.DECLINED:
        await activate(stage, record.call_id)
    original_send = transport.send_state

    async def fail_state(item):
        if item.state is target:
            raise RuntimeError("terminal state output failed")
        await original_send(item)

    monkeypatch.setattr(transport, "send_state", fail_state)
    reason = CallEndReason.DECLINED if target is CallState.DECLINED else CallEndReason.USER_HANGUP
    snapshot = await stage.terminate(reason)
    assert repository.find_by_id(record.call_id).state is CallState.ENDED
    assert settlement.snapshots == [snapshot]
    assert provider.closed and stage.context is None
    assert released == [ownership]
    assert not stage.tasks
    assert await stage.wait_realtime_stopped() is snapshot
    repository._sql_session_factory.kw["bind"].dispose()


async def assert_terminal(stage, repository, record, ownership, provider, transport, settlement, released):
    assert stage._transport_abort_task is not None
    try:
        await asyncio.shield(stage._transport_abort_task)
    except asyncio.CancelledError:
        pass
    await stage.terminate()
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
    assert stage._transport_abort_task.cancelled()


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
async def test_user_interrupt_during_real_audio_backpressure_keeps_call_active(
    tmp_path,
):
    from support.call_protocol import ProtocolDriver, StageOutputDriver

    from src.adapter.websocket.call_v1._audio_codec import WireAudioFrame

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
                    session._send_audio(
                        WireAudioFrame(
                            1,
                            2,
                            0,
                            message["stream_id"],
                            session._next_server_seq,
                            b"\0" * 16000,
                        )
                    )
            if message["type"] == "playback.stop":
                stopped.set()

    bridge = StageOutputDriver(call_id=str(record.call_id), deliver=deliver)
    session = ProtocolDriver(
        call_id=str(record.call_id),
        user_id="user",
        character_id="luotianyi",
        sink=bridge,
    )
    bridge.bind(stage=stage, session=session)
    stage._output_sink = output_sink(bridge)
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
