"""User facts, batch replies and delivery settlement through the real Agent."""

import asyncio

import pytest
from support.stage_lifecycle import finish_call, wait_call_finished

from src.domain.call.omni import TranscriptFinal
from src.domain.call import CallAudioSemantic, CallReplyStatus
from src.domain.stage.lifecycle import StageEndReason
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
    await _eventually(lambda: not stage._fact_tasks)


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
    waiter = asyncio.create_task(finish_call(stage, StageEndReason.USER_REQUESTED))
    await _eventually(lambda: stage.termination_requested)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert not stage._lifetime.termination.done()
    release.set()
    snapshot = await asyncio.wait_for(wait_call_finished(stage), 1)
    assert captured == ["用户说：“must survive hangup”"]
    assert snapshot.completed_turns[0].user_semantic in captured[0]
    assert stage.context is None
    assert not stage._fact_tasks
    assert not stage.tasks
    await stage._on_omni_event(TranscriptFinal("b", "too late"))
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
        await stage._on_omni_event(TranscriptFinal("b", "later successful fact"))
    release.set()
    snapshot = await asyncio.wait_for(wait_call_finished(stage), 1)
    result = await stage.terminate(StageEndReason.SYSTEM_FAILURE)
    assert result.finalization_error is not None and result.resources_released
    assert endings == saved == [snapshot]
    assert snapshot.completed_turns[0].user_semantic == "accepted despite write failure"
    assert len(snapshot.completed_turns) == (2 if with_later_input else 1)
    assert stage.context is None and not stage.tasks
