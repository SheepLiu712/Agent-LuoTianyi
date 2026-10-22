"""User facts, batch replies and delivery settlement through the real Agent."""

import asyncio

import pytest

from src.domain.call import CallAudioSemantic, CallEndReason, CallReplyStatus
from src.infrastructure.models.realtime_speech import SpeechStarted, SpeechStopped, TurnCompleted, TurnInvalid
from tests.integration.stage import test_call_stage as base
from tests.integration.stage.test_call_stage import _create, _eventually

call_setup = base.call_setup


def completed(text, item):
    return TurnCompleted(CallAudioSemantic(transcript=text), item)


async def finish_reply(stage):
    await _eventually(lambda: bool(stage._playback.pending_streams))
    await _eventually(lambda: stage._realize_task.done())
    for response_id, stream_id in stage._playback.pending_streams:
        stage.playback_completed(response_id, stream_id)
    await _eventually(lambda: not stage._inputs.pending)
    await _eventually(lambda: not stage._fact_tasks)


@pytest.mark.asyncio
async def test_back_to_back_speech_never_cancels_input_acceptance_and_merges_reply(call_setup, monkeypatch):
    stage, provider, _, handler = await _create(call_setup)
    entered, release = asyncio.Event(), asyncio.Event()
    append = stage.context.conversation.append

    async def blocked(entries):
        if entries[0].entry_id == "call-turn-1-user":
            entered.set()
            await release.wait()
        await append(entries)

    monkeypatch.setattr(stage.context.conversation, "append", blocked)
    handler.gate.set()
    try:
        await provider.emit(completed("first", "a"))
        await entered.wait()
        await provider.emit(SpeechStarted("b"))
        await provider.emit(SpeechStopped("b"))
        await provider.emit(completed("second", "b"))
        await _eventually(lambda: len(stage._turns) == 2)
        assert handler.requests == []
        release.set()
        await _eventually(lambda: len(handler.requests) == 1)
        request = handler.requests[0]
        assert [i.turn_seq for i in request.interaction.pending_stimuli] == [1, 2]
        assert [e.content.text for e in stage.context.conversation.read_working().entries] == [
            "用户说：“first”",
            "用户说：“second”",
        ]
        await finish_reply(stage)
        assert [t.status for t in stage._turns.values()] == [CallReplyStatus.COMPLETED] * 2
        assert len(stage.context.conversation.read_working().entries) == 3
        snapshot = await stage.terminate(CallEndReason.USER_HANGUP)
        assert len(snapshot.completed_turns) == 2
        assert snapshot.completed_turns[0].reply_turn_seq == 2
        assert snapshot.completed_turns[1].confirmed_agent_text == "正式回答"
    finally:
        release.set()
        await stage.terminate()


@pytest.mark.asyncio
@pytest.mark.parametrize("resume_before_stop", [False, True])
async def test_resume_waits_for_final_transcript_then_replies_once_to_all_pending(call_setup, resume_before_stop):
    stage, provider, _, handler = await _create(call_setup)
    handler.gate.set()
    try:
        await stage.disconnect()
        await provider.emit(completed("offline first", "a"))
        await provider.emit(SpeechStarted("b"))
        await _eventually(lambda: stage._inputs.ready == {1})
        if resume_before_stop:
            assert await stage.resume()
        await provider.emit(SpeechStopped("b"))
        await _eventually(lambda: not stage._user_speaking)
        if not resume_before_stop:
            assert await stage.resume()
        await asyncio.sleep(0.01)
        assert handler.requests == [], "speech stop does not mean final transcript is ready"
        await provider.emit(completed("offline second", "b"))
        await _eventually(lambda: len(handler.requests) == 1)
        assert [i.turn_seq for i in handler.requests[0].interaction.pending_stimuli] == [1, 2]
        await provider.emit(completed("offline second", "b"))
        await finish_reply(stage)
        assert len(handler.requests) == 1
        assert len(stage._turns) == 2
    finally:
        await stage.terminate()


@pytest.mark.asyncio
async def test_invalid_speech_after_resume_releases_previous_unanswered_input(call_setup):
    stage, provider, _, handler = await _create(call_setup)
    handler.gate.set()
    try:
        await stage.disconnect()
        await provider.emit(completed("pending", "a"))
        await provider.emit(SpeechStarted("noise"))
        await _eventually(lambda: stage._inputs.ready == {1})
        assert await stage.resume()
        await provider.emit(TurnInvalid("empty_transcript", "noise"))
        await _eventually(lambda: len(handler.requests) == 1)
        await finish_reply(stage)
    finally:
        await stage.terminate()


@pytest.mark.asyncio
async def test_generation_and_send_do_not_consume_inputs_or_append_unheard_reply(call_setup):
    stage, provider, _, handler = await _create(call_setup)
    handler.gate.set()
    try:
        await provider.emit(completed("question", "a"))
        await _eventually(lambda: bool(stage._playback.pending_streams))
        await _eventually(lambda: stage._realize_task.done())
        response_id, stream_id = stage._playback.pending_streams[0]
        stage.audio_sent(response_id)
        assert list(stage._inputs.pending) == [1]
        assert len(stage.context.conversation.read_working().entries) == 1
        await stage.disconnect()
        assert await stage.resume()
        await asyncio.sleep(0.01)
        assert len(handler.requests) == 1, "resume must not regenerate a reply still awaiting playback"
        stage.playback_completed(response_id, stream_id)
        stage.playback_completed(response_id, stream_id)
        await _eventually(lambda: not stage._inputs.pending)
        assert len(stage.context.conversation.read_working().entries) == 2
    finally:
        await stage.terminate()


@pytest.mark.asyncio
async def test_interrupted_delivery_keeps_pending_and_late_completion_cannot_answer_it(call_setup):
    stage, provider, _, handler = await _create(call_setup)
    handler.gate.set()
    try:
        await provider.emit(completed("first", "a"))
        await _eventually(lambda: bool(stage._playback.pending_streams))
        await _eventually(lambda: stage._realize_task.done())
        response_id, stream_id = stage._playback.pending_streams[0]
        await provider.emit(SpeechStarted("b"))
        await _eventually(lambda: response_id in stage._tombstones)
        stage.playback_stopped(response_id, stream_id)
        stage.playback_completed(response_id, stream_id)
        assert list(stage._inputs.pending) == [1]
        assert len(stage.context.conversation.read_working().entries) == 1
        await provider.emit(completed("second", "b"))
        await _eventually(lambda: len(handler.requests) == 2)
        assert handler.requests[-1].stimulus.interrupted
        assert [i.turn_seq for i in handler.requests[-1].interaction.pending_stimuli] == [1, 2]
        await finish_reply(stage)
    finally:
        await stage.terminate()


@pytest.mark.asyncio
async def test_complete_termination_drains_accepted_fact_even_when_waiter_is_cancelled(call_setup, monkeypatch):
    stage, provider, _, handler = await _create(call_setup)
    entered, release = asyncio.Event(), asyncio.Event()
    append = stage.context.conversation.append
    context = stage.context
    captured = []

    async def blocked(entries):
        entered.set()
        await release.wait()
        await append(entries)
        captured.extend(e.content.text for e in context.conversation.read_working().entries)

    monkeypatch.setattr(context.conversation, "append", blocked)
    await provider.emit(completed("must survive hangup", "a"))
    await entered.wait()
    waiter = asyncio.create_task(stage.terminate(CallEndReason.USER_HANGUP))
    await _eventually(lambda: stage.termination_requested)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert not stage._termination.done()
    release.set()
    snapshot = await asyncio.wait_for(stage.wait_closed(), 1)
    assert captured == ["用户说：“must survive hangup”"]
    assert snapshot.completed_turns[0].user_semantic == captured[0]
    assert handler.requests == []
    assert stage.context is None
    assert not stage._fact_tasks
    assert not stage.tasks
    await stage._on_turn(completed("too late", "b"))
    assert len(snapshot.completed_turns) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("with_later_input", [False, True])
async def test_failed_context_append_still_runs_ending_and_history_before_releasing(
    call_setup, monkeypatch, with_later_input
):
    stage, provider, _, _ = await _create(call_setup)
    endings, saved = [], []
    ending = stage._complete_ending
    append = stage.context.conversation.append
    entered, release = asyncio.Event(), asyncio.Event()

    async def failed_append(entries):
        if entries[0].entry_id == "call-turn-1-user":
            entered.set()
            await release.wait()
            raise RuntimeError("test context write failure")
        await append(entries)

    async def observe_ending(snapshot):
        endings.append(snapshot)
        return await ending(snapshot)

    async def save(snapshot, *, result):
        saved.append(snapshot)

    monkeypatch.setattr(stage.context.conversation, "append", failed_append)
    monkeypatch.setattr(stage, "_complete_ending", observe_ending)
    stage._save_history = save
    await provider.emit(completed("accepted despite write failure", "a"))
    await entered.wait()
    if with_later_input:
        await stage._on_turn(completed("later successful fact", "b"))
    release.set()
    snapshot = await asyncio.wait_for(stage.wait_closed(), 1)
    with pytest.raises(RuntimeError, match="call fact could not be accepted"):
        await stage.terminate()
    assert endings == saved == [snapshot]
    assert snapshot.completed_turns[0].user_semantic == "用户说：“accepted despite write failure”"
    assert len(snapshot.completed_turns) == (2 if with_later_input else 1)
    assert stage.context is None and not stage.tasks
