"""Deadline reminders through real Agent, TTS output and playback settlement."""

import asyncio
import time

import pytest
from support.call_apology import catalog

import src.domain.agent as d
from src.agent.handlers.action.router import ActionRouter
from src.agent.handlers.action.say import SayHandler
from src.agent.handlers.stimulus.call import CallTimeLimitWarningHandler
from src.domain.call import CallEndReason, CallState
from src.infrastructure.models.realtime_speech import SpeechStarted, SpeechStopped, TurnInvalid
from src.stage._call_warning import WarningState
from tests.integration.stage import test_call_stage as base
from tests.integration.stage.test_call_failure_policy import Speech
from tests.integration.stage.test_call_pending_inputs import completed, finish_reply
from tests.integration.stage.test_call_stage import _eventually

call_setup = base.call_setup
WARNING = "通话时间快到了，我们很快就要结束啦。"


async def setup(call_setup, tmp_path, *, failures=0, config=None):
    stage, provider, transport, reply = await base._create(
        call_setup, config=config, time_limit_handler=CallTimeLimitWarningHandler()
    )
    speech = Speech(failures=failures)
    stage._agent._action_router = ActionRouter(
        (
            (d.ActionKind.SAY, SayHandler("luotianyi", speech, catalog(tmp_path))),
            (d.ActionKind.COGNITIVE_MAINTENANCE, base._NoOutputActionHandler()),
        )
    )
    reply.gate.set()
    return stage, provider, transport, reply, speech


async def due(stage, clock, *, seconds=1770):
    clock.advance(seconds)
    stage._time_limit_changed.set()
    await _eventually(lambda: stage._warning.state is not WarningState.NOT_DUE)


async def warning_stream(stage):
    await _eventually(
        lambda: any(
            r.request_id == stage._warning.request_id and r.message_completed and not r.failed
            for r in stage._responses.values()
        )
    )
    await _eventually(lambda: stage._realize_task.done())
    return next(
        (identity, r.stream_id)
        for identity, r in stage._responses.items()
        if r.request_id == stage._warning.request_id and not r.failed
    )


def texts(stage):
    return [e.content.text for e in stage.context.conversation.read_working().entries]


@pytest.mark.asyncio
@pytest.mark.parametrize("warning_seconds", [0, 0.1])
async def test_real_timer_timeout_triggers_warning_and_deadline_without_external_wakeup(
    call_setup, tmp_path, warning_seconds
):
    clock = call_setup[-1]
    started = time.monotonic()
    clock.tick = lambda: 100 + time.monotonic() - started
    stage, _, _, _, speech = await setup(
        call_setup, tmp_path, config={"time_limit_seconds": 0.2, "time_limit_warning_seconds": warning_seconds}
    )
    try:
        snapshot = await asyncio.wait_for(stage.wait_closed(), 2)
        assert snapshot.terminal.end_reason is CallEndReason.TIME_LIMIT
        assert snapshot.terminal.active_duration_ms >= 200
        assert speech.calls[WARNING] == (1 if warning_seconds else 0)
        assert not stage.tasks
    finally:
        await stage.terminate()


@pytest.mark.asyncio
async def test_default_warning_waits_for_final_and_fact_then_precedes_batch_reply(call_setup, tmp_path, monkeypatch):
    stage, provider, _, reply, speech = await setup(call_setup, tmp_path)
    clock = call_setup[-1]
    entered, release = asyncio.Event(), asyncio.Event()
    append = stage.context.conversation.append

    async def blocked(entries):
        if entries[0].entry_id == "call-turn-1-user":
            entered.set()
            await release.wait()
        await append(entries)

    monkeypatch.setattr(stage.context.conversation, "append", blocked)
    try:
        await provider.emit(SpeechStarted("a"))
        await _eventually(lambda: stage._user_speaking)
        await due(stage, clock)
        assert speech.calls == {}
        await provider.emit(SpeechStopped("a"))
        await _eventually(lambda: not stage._user_speaking)
        await asyncio.sleep(0.01)
        assert speech.calls == {}, "speech stop must wait for the final transcript"
        await provider.emit(completed("question A", "a"))
        await asyncio.wait_for(entered.wait(), 1)
        assert speech.calls == {}
        release.set()
        stream = await warning_stream(stage)
        assert texts(stage) == ["用户说：“question A”"]
        assert list(stage._inputs.pending) == [1] and reply.requests == []
        stage.playback_completed(*stream)
        stage.playback_completed(*stream)
        await _eventually(lambda: len(reply.requests) == 1)
        assert texts(stage).count(WARNING) == 1
        assert [i.turn_seq for i in reply.requests[0].interaction.pending_stimuli] == [1]
        await finish_reply(stage)
        assert texts(stage) == ["用户说：“question A”", WARNING, "正式回答"]
        assert speech.calls[WARNING] == 1
        clock.advance(30)
        stage._time_limit_changed.set()
        snapshot = await asyncio.wait_for(stage.wait_closed(), 1)
        assert snapshot.terminal.end_reason is CallEndReason.TIME_LIMIT
        assert snapshot.terminal.active_duration_ms == 1_800_000
        assert not stage.tasks
    finally:
        release.set()
        await stage.terminate()


@pytest.mark.asyncio
async def test_each_interruption_requeues_warning_and_old_receipts_cannot_settle_new_attempt(call_setup, tmp_path):
    stage, provider, _, reply, speech = await setup(call_setup, tmp_path)
    try:
        await due(stage, call_setup[-1])
        first = await warning_stream(stage)
        for index in range(2):
            old = await warning_stream(stage)
            await provider.emit(SpeechStarted(f"user-{index}"))
            await _eventually(lambda: stage._warning.state is WarningState.PENDING)
            stage.playback_stopped(*old)
            stage.playback_completed(*old)
            await provider.emit(SpeechStopped(f"user-{index}"))
            await _eventually(lambda: not stage._user_speaking)
            assert stage._warning.state is WarningState.PENDING
            await provider.emit(completed(f"question {index}", f"user-{index}"))
            new = await warning_stream(stage)
            assert new != old
            stage.playback_completed(*old)
            await asyncio.sleep(0)
            assert stage._warning.state is WarningState.IN_FLIGHT
            assert texts(stage).count(WARNING) == 0
        assert speech.calls[WARNING] == 3
        assert list(stage._inputs.pending) == [1, 2] and reply.requests == []
        stage.playback_completed(*new)
        await _eventually(lambda: stage._warning.state is WarningState.DELIVERED)
        await _eventually(lambda: len(reply.requests) == 1)
        assert [i.turn_seq for i in reply.requests[0].interaction.pending_stimuli] == [1, 2]
        await finish_reply(stage)
        stage.playback_completed(*first)
        assert texts(stage).count(WARNING) == 1
    finally:
        await stage.terminate()


@pytest.mark.asyncio
async def test_accepted_completion_pending_fact_is_not_replayed_after_speech_start(call_setup, tmp_path, monkeypatch):
    stage, provider, _, _, speech = await setup(call_setup, tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    append = stage.context.conversation.append

    async def blocked(entries):
        if entries[0].content.text == WARNING:
            entered.set()
            await release.wait()
        await append(entries)

    monkeypatch.setattr(stage.context.conversation, "append", blocked)
    try:
        await due(stage, call_setup[-1])
        stream = await warning_stream(stage)
        stage.playback_completed(*stream)
        await asyncio.wait_for(entered.wait(), 1)
        await provider.emit(SpeechStarted("noise"))
        await _eventually(lambda: stage._user_speaking)
        assert stage._warning.state is WarningState.IN_FLIGHT
        await provider.emit(TurnInvalid("empty_transcript", "noise"))
        await _eventually(lambda: not stage._user_speaking)
        release.set()
        await _eventually(lambda: stage._warning.state is WarningState.DELIVERED)
        await asyncio.sleep(0.01)
        assert speech.calls[WARNING] == 1
        assert texts(stage) == [WARNING]
    finally:
        release.set()
        await stage.terminate()


@pytest.mark.asyncio
async def test_warning_does_not_interrupt_existing_reply_or_consume_its_pending_input(call_setup, tmp_path):
    stage, provider, _, reply, speech = await setup(call_setup, tmp_path)
    try:
        await provider.emit(completed("question", "a"))
        await _eventually(lambda: bool(stage._playback.pending_streams) and stage._realize_task.done())
        stream = stage._playback.pending_streams[0]
        await due(stage, call_setup[-1])
        assert stage._warning.state is WarningState.PENDING
        assert speech.calls[WARNING] == 0
        assert stream[0] not in stage._tombstones
        stage.playback_completed(*stream)
        await _eventually(lambda: not stage._inputs.pending)
        warning = await warning_stream(stage)
        stage.playback_completed(*warning)
        await _eventually(lambda: stage._warning.state is WarningState.DELIVERED)
        assert texts(stage) == ["用户说：“question”", "正式回答", WARNING]
        assert len(reply.requests) == 1
    finally:
        await stage.terminate()


@pytest.mark.asyncio
async def test_warning_keeps_same_attempt_during_reconnect(call_setup, tmp_path):
    stage, _, _, _, speech = await setup(call_setup, tmp_path)
    try:
        await due(stage, call_setup[-1])
        stream = await warning_stream(stage)
        identity = stage._warning.request_id
        await stage.disconnect()
        call_setup[-1].advance(1)
        assert await stage.resume()
        await asyncio.sleep(0.01)
        assert stage._warning.request_id == identity
        assert speech.calls[WARNING] == 1
        stage.playback_completed(*stream)
        await _eventually(lambda: stage._warning.state is WarningState.DELIVERED)
        assert texts(stage) == [WARNING]
    finally:
        await stage.terminate()


@pytest.mark.asyncio
async def test_deadline_cancels_blocked_tts_without_waiting_for_playback(call_setup, tmp_path):
    stage, _, _, _, speech = await setup(call_setup, tmp_path)
    entered, cancelled = asyncio.Event(), asyncio.Event()

    async def blocked(*args, **kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
            yield None
        finally:
            cancelled.set()

    speech.speak = blocked
    try:
        await due(stage, call_setup[-1])
        await asyncio.wait_for(entered.wait(), 1)
        assert stage._warning.state is WarningState.IN_FLIGHT
        call_setup[-1].advance(30)
        stage._time_limit_changed.set()
        snapshot = await asyncio.wait_for(stage.wait_closed(), 1)
        assert snapshot.terminal.end_reason is CallEndReason.TIME_LIMIT
        assert cancelled.is_set() and not stage.tasks
    finally:
        await stage.terminate()


@pytest.mark.asyncio
async def test_warning_can_be_disabled_without_disabling_deadline(call_setup, tmp_path):
    stage, _, _, _, speech = await setup(
        call_setup, tmp_path, config={"time_limit_seconds": 10, "time_limit_warning_seconds": 0}
    )
    try:
        call_setup[-1].advance(10)
        stage._time_limit_changed.set()
        snapshot = await asyncio.wait_for(stage.wait_closed(), 1)
        assert snapshot.terminal.end_reason is CallEndReason.TIME_LIMIT
        assert speech.calls == {}
        assert stage._warning.state is WarningState.NOT_DUE
        assert not stage.tasks
    finally:
        await stage.terminate()


@pytest.mark.asyncio
async def test_warning_due_offline_waits_for_resumed_speech_and_invalid_final(call_setup, tmp_path):
    stage, provider, _, _, speech = await setup(call_setup, tmp_path)
    try:
        clock = call_setup[-1]
        clock.advance(1769)
        await stage.disconnect()
        await provider.emit(SpeechStarted("noise"))
        await _eventually(lambda: stage._user_speaking)
        await due(stage, clock, seconds=1)
        assert speech.calls == {}
        assert await stage.resume()
        await provider.emit(SpeechStopped("noise"))
        await _eventually(lambda: not stage._user_speaking)
        await asyncio.sleep(0.01)
        assert speech.calls == {}
        await provider.emit(TurnInvalid("empty_transcript", "noise"))
        stream = await warning_stream(stage)
        stage.playback_completed(*stream)
        await _eventually(lambda: stage._warning.state is WarningState.DELIVERED)
        assert texts(stage) == [WARNING] and not stage._inputs.pending
    finally:
        await stage.terminate()


@pytest.mark.asyncio
@pytest.mark.parametrize("failures", [1, 2])
async def test_warning_tts_retries_once_and_exhaustion_does_not_loop_or_count_as_reply_failure(
    call_setup, tmp_path, failures
):
    stage, _, _, _, speech = await setup(call_setup, tmp_path, failures=failures)
    try:
        stage._reply_failures = 1
        await due(stage, call_setup[-1])
        await _eventually(lambda: speech.calls[WARNING] == 2 and stage._realize_task.done())
        for identity, stream in tuple(stage._playback.pending_streams):
            if stage._responses[identity].failed:
                stage.playback_stopped(identity, stream)
            else:
                stage.playback_completed(identity, stream)
        expected = WarningState.DELIVERED if failures == 1 else WarningState.FAILED
        await _eventually(lambda: stage._warning.state is expected)
        assert stage._reply_failures == 1
        assert texts(stage) == ([WARNING] if failures == 1 else [])
        stage._schedule_output()
        await asyncio.sleep(0.01)
        assert speech.calls[WARNING] == 2
        call_setup[-1].advance(30)
        stage._time_limit_changed.set()
        snapshot = await asyncio.wait_for(stage.wait_closed(), 1)
        assert snapshot.terminal.end_reason is CallEndReason.TIME_LIMIT
        assert not stage.tasks
    finally:
        await stage.terminate()


@pytest.mark.asyncio
async def test_deadline_drops_waiting_warning_and_owned_termination_drains_input(call_setup, tmp_path, monkeypatch):
    stage, provider, _, reply, speech = await setup(call_setup, tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    context = stage.context
    append = context.conversation.append
    captured = []

    async def blocked(entries):
        entered.set()
        await release.wait()
        await append(entries)
        captured.extend(e.content.text for e in context.conversation.read_working().entries)

    monkeypatch.setattr(context.conversation, "append", blocked)
    await provider.emit(SpeechStarted("a"))
    await _eventually(lambda: stage._user_speaking)
    await due(stage, call_setup[-1])
    await provider.emit(completed("accepted at deadline", "a"))
    await asyncio.wait_for(entered.wait(), 1)
    try:
        call_setup[-1].advance(30)
        stage._time_limit_changed.set()
        await _eventually(lambda: stage.termination_requested)
        waiter = asyncio.create_task(stage.terminate())
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert not stage._termination.done()
        assert speech.calls == {} and reply.requests == []
        release.set()
        snapshot = await asyncio.wait_for(stage.wait_closed(), 1)
        assert captured == ["用户说：“accepted at deadline”"]
        assert snapshot.terminal.end_reason is CallEndReason.TIME_LIMIT
        assert snapshot.completed_turns[0].user_semantic == captured[0]
        assert not stage.tasks and stage.context is None
    finally:
        release.set()
        await stage.terminate()


@pytest.mark.asyncio
@pytest.mark.parametrize("resume", [False, True])
async def test_recovery_window_survives_deadline_without_late_warning(call_setup, tmp_path, resume):
    stage, provider, _, _, speech = await setup(call_setup, tmp_path)
    clock = call_setup[-1]
    try:
        await provider.emit(SpeechStarted("still-speaking"))
        await _eventually(lambda: stage._user_speaking)
        await due(stage, clock)
        clock.advance(29)
        await stage.disconnect()
        clock.advance(1.5)
        stage._time_limit_changed.set()
        await asyncio.sleep(0.01)
        assert stage.state is CallState.RECONNECTING and not stage.termination_requested
        if resume:
            assert await stage.resume()
        else:
            clock.advance(1.5)
            await stage.expire_retention(stage._recovery_deadline)
        snapshot = await asyncio.wait_for(stage.wait_closed(), 1)
        assert snapshot.terminal.end_reason is (CallEndReason.TIME_LIMIT if resume else CallEndReason.RECOVERY_TIMEOUT)
        assert snapshot.terminal.active_duration_ms == (1_800_500 if resume else 1_799_000)
        assert speech.calls == {} and not stage.tasks
    finally:
        await stage.terminate()
