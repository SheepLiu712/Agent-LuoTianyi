from collections import Counter
from types import SimpleNamespace

import pytest
from support.call_apology import Recall, Replies, catalog

import src.domain.agent as d
from src.agent.handlers.action.router import ActionRouter
from src.agent.handlers.action.say import SayHandler
from src.agent.handlers.stimulus.call import (
    CallReplyConfirmedHandler,
    CallReplyRequestedHandler,
    CallTurnCompletedHandler,
)
from src.agent.skills.expression.prepared_speech import PreparedSpeechCatalog
from src.domain.call import CallAudioSemantic, CallEndReason, CallReplyStatus, CallState, RecallMode
from src.infrastructure.models.realtime_speech import SpeechStarted, TurnCompleted
from src.stage.call_stage import CallReplyFailed
from tests.integration.stage import test_call_stage as base
from tests.integration.stage.test_call_stage import _agent, _create, _eventually

call_setup = base.call_setup


class Speech:
    def __init__(self, *, failures=0):
        self.failures = failures
        self.calls = Counter()

    async def speak(self, invocation, *, text, tone, output_format):
        self.calls[text] += 1
        for _ in range(2):
            yield SimpleNamespace(data=b"\0\0" * 10, framing=d.AudioFraming.RAW_PCM)
        if self.calls[text] <= self.failures:
            raise RuntimeError("TTS failed after partial audio")


async def setup(call_setup, tmp_path, *, failing=False, failures=0, texts=("answer",)):
    stage, provider, transport, _ = await _create(call_setup)
    replies, speech = Replies(failing=failing, texts=texts), Speech(failures=failures)
    stage._agent = _agent(CallReplyRequestedHandler(Recall(), replies, catalog(tmp_path)))
    stage._agent._action_router = ActionRouter(
        (
            (d.ActionKind.SAY, SayHandler("luotianyi", speech, catalog(tmp_path))),
            (d.ActionKind.COGNITIVE_MAINTENANCE, base._NoOutputActionHandler()),
        )
    )
    return stage, transport, replies, speech


async def turn(stage, text="user"):
    seq = len(stage._turns) + 1
    await stage._on_turn(TurnCompleted(CallAudioSemantic(transcript=text)))
    await _eventually(lambda: seq in stage._request_turn.values())
    await _eventually(lambda: not stage._handle_tasks and (stage._realize_task is None or stage._realize_task.done()))
    await _eventually(lambda: not stage._fact_tasks)


async def acknowledge(stage):
    for response_id, stream_id in tuple(stage._playback.pending_streams):
        if stage._responses[response_id].failed:
            stage.playback_stopped(response_id, stream_id)
        else:
            stage.playback_completed(response_id, stream_id)
    await _eventually(lambda: not stage._fact_tasks)


@pytest.mark.asyncio
async def test_partial_formal_reply_is_preserved_but_batch_waits_for_next_reply(call_setup, tmp_path):
    from src.agent.skills.cognitive.call_settlement import render_call_turns

    stage, _, replies, _ = await setup(call_setup, tmp_path, texts=("confirmed first", "unheard second"))
    try:
        await turn(stage, "question A")
        streams = tuple(stage._playback.pending_streams)
        assert len(streams) == 2
        stage.playback_completed(*streams[0])
        await _eventually(lambda: not stage._fact_tasks)
        assert list(stage._inputs.pending) == [1]
        assert [e.content.text for e in stage.context.conversation.read_working().entries] == [
            "用户说：“question A”",
            "confirmed first",
        ]
        await stage._provider.emit(SpeechStarted("next"))
        await _eventually(lambda: streams[1][0] in stage._tombstones)
        stage.playback_stopped(*streams[1])
        stage.playback_completed(*streams[1])
        replies.texts = ("combined answer",)
        requests = []
        generate = replies.generate

        async def observed(*args, **kwargs):
            requests.append(kwargs)
            return await generate(*args, **kwargs)

        replies.generate = observed
        await stage._on_turn(TurnCompleted(CallAudioSemantic(transcript="question B"), "next"))
        await _eventually(lambda: bool(requests))
        assert "question A" in requests[0]["reply_topic"] and "question B" in requests[0]["reply_topic"]
        assert "confirmed first" in requests[0]["conversation_history"]
        assert "unheard second" not in requests[0]["conversation_history"]
        await _eventually(lambda: not stage._handle_tasks and stage._realize_task.done())
        await acknowledge(stage)
        assert not stage._inputs.pending
        final = await stage.terminate(CallEndReason.USER_HANGUP)
        text = "\n".join(render_call_turns(final))
        assert text.count("confirmed first") == text.count("combined answer") == 1
        assert "unheard second" not in text
    finally:
        await stage.terminate()


@pytest.mark.parametrize("rate,width,channels", [(16000, 2, 1), (24000, 1, 1), (24000, 2, 2)])
def test_invalid_apology_cannot_enable_calls(tmp_path, rate, width, channels):
    assert not catalog(tmp_path, rate=rate, width=width, channels=channels).supports_call_apology("luotianyi")


def test_missing_and_valid_apology(tmp_path):
    assert not PreparedSpeechCatalog({}).supports_call_apology("luotianyi")
    assert catalog(tmp_path).supports_call_apology("luotianyi")


@pytest.mark.asyncio
async def test_reply_failure_plays_prepared_apology_and_second_failure_ends(call_setup, tmp_path):
    stage, transport, _, speech = await setup(call_setup, tmp_path, failing=True)
    await turn(stage)
    assert stage.state is CallState.ACTIVE
    assert any(item[0] == "pcm" for item in transport.items if isinstance(item, tuple))
    assert not speech.calls
    await acknowledge(stage)
    assert stage._reply_failures == 1
    assert stage._turns[1].status is CallReplyStatus.FAILED
    await turn(stage)
    await _eventually(lambda: stage.snapshot is not None)
    assert stage.snapshot.terminal.end_reason is CallEndReason.SYSTEM_FAILURE


@pytest.mark.asyncio
async def test_each_utterance_retries_partial_tts_with_new_response(call_setup, tmp_path):
    stage, transport, _, speech = await setup(call_setup, tmp_path, failures=1, texts=("first", "second"))
    await turn(stage)
    assert speech.calls == {"first": 2, "second": 2}
    starts = [item for item in transport.items if isinstance(item, tuple) and item[0] == "start"]
    stops = [item for item in transport.items if isinstance(item, tuple) and item[0] == "stop"]
    assert len(starts) == 4 and len({item[1] for item in starts}) == 4
    assert len(stops) == 2
    assert not any(isinstance(item, CallReplyFailed) for item in transport.items)
    await acknowledge(stage)
    final = await stage.terminate(CallEndReason.USER_HANGUP)
    assert final.completed_turns[0].formal_agent_text == "first\nsecond"
    assert final.completed_turns[0].reply_status is CallReplyStatus.COMPLETED


@pytest.mark.asyncio
async def test_tts_exhausted_is_one_failure_and_success_resets(call_setup, tmp_path):
    stage, transport, replies, speech = await setup(call_setup, tmp_path, failures=2)
    await turn(stage)
    assert speech.calls["answer"] == 2
    assert stage.state is CallState.ACTIVE
    assert stage._reply_failures == 1
    assert sum(isinstance(item, CallReplyFailed) for item in transport.items) == 1
    await acknowledge(stage)
    speech.failures = 0
    await turn(stage)
    await acknowledge(stage)
    assert stage._reply_failures == 0
    replies.failing = True
    await turn(stage)
    assert stage.state is CallState.ACTIVE
    assert stage._reply_failures == 1
    await stage.terminate(CallEndReason.USER_HANGUP)


@pytest.mark.asyncio
async def test_failure_after_reply_failure_ends_and_excludes_failed_text(call_setup, tmp_path):
    stage, _, replies, _ = await setup(call_setup, tmp_path, failing=True, failures=2)
    await turn(stage)
    await acknowledge(stage)
    replies.failing = False
    await turn(stage)
    await _eventually(lambda: stage.snapshot is not None)
    assert stage.snapshot.terminal.end_reason is CallEndReason.SYSTEM_FAILURE
    assert all(item.formal_agent_text is None for item in stage.snapshot.completed_turns)


@pytest.mark.asyncio
async def test_playback_receipt_before_message_end_still_settles(call_setup, tmp_path):
    stage, _, _, _ = await setup(call_setup, tmp_path)
    stage._reply_failures = 1
    original = stage.playback_final

    def finish(response_id, stream_id):
        original(response_id, stream_id)
        stage.playback_completed(response_id, stream_id)

    stage.playback_final = finish
    await turn(stage)
    assert stage._reply_failures == 0
    assert stage._turns[1].status is CallReplyStatus.COMPLETED
    await stage.terminate(CallEndReason.USER_HANGUP)


@pytest.mark.asyncio
async def test_retry_provisional_remains_formal_reply_barrier(call_setup, tmp_path):
    from src.domain.call import AckStyle

    class Recalling(Recall):
        async def decide(self, *args, **kwargs):
            return SimpleNamespace(mode=RecallMode.RECALL, ack_style=AckStyle.THINKING, memory_queries=("query",))

        async def recall_once(self, *args, **kwargs):
            return ()

    stage, _, replies, speech = await setup(call_setup, tmp_path, failures=1)
    stage._agent._stimulus_router = base.StimulusRouter(
        (
            (d.StimulusKind.CALL_TURN_COMPLETED, CallTurnCompletedHandler()),
            (d.StimulusKind.CALL_REPLY_CONFIRMED, CallReplyConfirmedHandler()),
            (d.StimulusKind.CALL_REPLY_REQUESTED, CallReplyRequestedHandler(Recalling(), replies, catalog(tmp_path))),
            (d.StimulusKind.CALL_ENDING, base._NoPlanHandler()),
        )
    )
    await stage._on_turn(TurnCompleted(CallAudioSemantic(transcript="user")))
    await _eventually(
        lambda: any(response.message_completed and response.provisional for response in stage._responses.values())
    )
    for response_id, stream_id in tuple(stage._playback.pending_streams):
        if stage._responses[response_id].failed:
            stage.playback_stopped(response_id, stream_id)
    assert "answer" not in speech.calls
    for response_id, stream_id in tuple(stage._playback.pending_streams):
        if stage._responses[response_id].provisional:
            stage.playback_completed(response_id, stream_id)
    await _eventually(lambda: stage._realize_task.done())
    assert speech.calls["answer"] == 2
    await acknowledge(stage)
    await stage.terminate(CallEndReason.USER_HANGUP)
