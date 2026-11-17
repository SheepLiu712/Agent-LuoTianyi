"""Persistent evidence for unified CallStage transport-abort behavior."""

import asyncio
import json

import pytest
from support.call_output import output_sink
from support.call_stage_failure_harness import activate, create_active_stage, eventually
from support.stage_lifecycle import finish_call, wait_call_finished, wait_interaction_end

from src.domain.call import CallAudioSemantic, CallEndReason, CallOutcome, CallState
from src.domain.stage.lifecycle import StageEndReason, StageLifecycleState
from src.infrastructure.models.realtime_speech import ProviderFailed, SpeechStarted, TurnCompleted


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
    reason = StageEndReason.AGENT_REQUESTED if target is CallState.DECLINED else StageEndReason.USER_REQUESTED
    ending = asyncio.create_task(stage.terminate(reason))
    try:
        await asyncio.wait_for(close_entered.wait(), 2)
        if cancel_owner:
            ending.cancel()
            await asyncio.sleep(0)
            await asyncio.sleep(0)
        assert stage.lifecycle_state is StageLifecycleState.TERMINATING
        assert not released
    finally:
        close_release.set()
    if cancel_owner:
        with pytest.raises(asyncio.CancelledError):
            await ending
    else:
        await ending
    result = await stage.terminate(reason)
    assert result.finalization_error == "RuntimeError" and result.resources_released
    assert provider.closed and stage.context is None
    with pytest.raises(RuntimeError, match="交互上下文已经释放"):
        context.conversation.read_working()
    assert released == [ownership]
    assert not stage.tasks
    assert stage.lifecycle_state is StageLifecycleState.TERMINATED
    assert not settlement.snapshots
    assert await wait_interaction_end(stage) is None
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
    ending = asyncio.create_task(stage.terminate(StageEndReason.USER_REQUESTED))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        ending.cancel()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert stage.lifecycle_state is StageLifecycleState.TERMINATING
        assert not released and not provider.closed
        context.conversation.read_working()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await ending
    await stage.terminate(StageEndReason.USER_REQUESTED)
    assert provider.closed and stage.context is None
    with pytest.raises(RuntimeError, match="交互上下文已经释放"):
        context.conversation.read_working()
    assert released == [ownership]
    assert not stage.tasks
    assert stage.lifecycle_state is StageLifecycleState.TERMINATED
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
    reason = StageEndReason.AGENT_REQUESTED if target is CallState.DECLINED else StageEndReason.USER_REQUESTED
    snapshot = await finish_call(stage, reason)
    assert repository.find_by_id(record.call_id).state is CallState.ENDED
    assert settlement.snapshots == [snapshot]
    assert provider.closed and stage.context is None
    assert released == [ownership]
    assert not stage.tasks
    assert stage.interaction_ended
    repository._sql_session_factory.kw["bind"].dispose()


async def assert_terminal(stage, repository, record, ownership, provider, transport, settlement, released):
    assert stage._transport_abort_task is not None
    try:
        await asyncio.shield(stage._transport_abort_task)
    except asyncio.CancelledError:
        pass
    await finish_call(stage)
    snapshot = stage.snapshot
    assert snapshot.terminal.outcome is CallOutcome.CONNECTED
    assert snapshot.terminal.end_reason is CallEndReason.SYSTEM_FAILURE
    assert repository.find_by_id(record.call_id).state is CallState.ENDED
    assert released == [ownership]
    assert provider.closed is True
    assert stage.context is None
    assert settlement.snapshots == [snapshot]
    assert transport.count("ended") == 1
    assert stage.lifecycle_state is StageLifecycleState.TERMINATED
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
    await wait_call_finished(stage)

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
    await wait_call_finished(stage)

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
    await wait_call_finished(stage)

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
    await wait_call_finished(stage)
    await asyncio.sleep(0)

    await assert_terminal(stage, repository, record, ownership, provider, transport, settlement, released)


@pytest.mark.asyncio
@pytest.mark.parametrize("trigger", ["interrupt", "hangup", "provider_failure", "time_limit"])
async def test_control_during_real_audio_backpressure_preserves_stream_retirement(tmp_path, trigger):
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
        if trigger != "interrupt":
            if trigger == "hangup":
                stage.begin_termination(StageEndReason.USER_REQUESTED)
                expected_reason = CallEndReason.USER_HANGUP
            elif trigger == "provider_failure":
                await provider.emit(ProviderFailed("provider unavailable", retryable=False))
                expected_reason = CallEndReason.PROVIDER_FAILED
            else:
                clock = stage._monotonic.__self__
                clock.monotonic += 1800
                stage._time_limit_changed.set()
                expected_reason = CallEndReason.TIME_LIMIT
            await asyncio.wait_for(wait_call_finished(stage), 2)
            assert stopped.is_set()
            assert stage.snapshot.terminal.end_reason is expected_reason
            assert transport_terminal(session)
            return
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
        await finish_call(stage)
        session.close()
        repository._sql_session_factory.kw["bind"].dispose()


def transport_terminal(session):
    outputs = [json.loads(item.text) for item in session.replay_after(0) if item.text]
    stop = next(item for item in outputs if item["type"] == "playback.stop")
    terminal = next(item for item in outputs if item["type"] == "call.ended")
    assert stop["retire_server_seq"]["through"] + 1 == stop["seq"]
    return stop["seq"] < terminal["seq"]
