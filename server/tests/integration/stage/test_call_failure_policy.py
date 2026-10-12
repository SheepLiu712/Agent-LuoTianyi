import json
import wave
from collections import Counter
from types import SimpleNamespace

import pytest

import src.domain.agent as d
from src.agent.handlers.action.router import ActionRouter
from src.agent.handlers.action.say import SayHandler
from src.agent.handlers.stimulus.call import CallTurnCompletedHandler
from src.agent.skills.contracts import ReplyDraft
from src.agent.skills.expression.prepared_speech import PreparedSpeechCatalog
from src.domain.call import CallAudioSemantic, CallEndReason, CallReplyStatus, CallState, RecallMode
from src.infrastructure.models.realtime_speech import TurnCompleted
from src.stage.call_stage import CallReplyFailed
from tests.integration.stage import test_call_stage as base
from tests.integration.stage.test_call_stage import _agent, _create, _eventually

call_setup = base.call_setup


def catalog(tmp_path, *, rate=24000, width=2, channels=1):
    with wave.open(str(tmp_path / "apology.wav"), "wb") as audio:
        audio.setparams((channels, width, rate, 0, "NONE", "not compressed"))
        audio.writeframes(b"\0" * 960 * width * channels)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps([dict(name="call_apology", audio_path="apology.wav", text="sorry", expression="normal")])
    )
    return PreparedSpeechCatalog({"luotianyi": {"manifest": str(manifest)}})


class Recall:
    async def decide(self, *args, **kwargs):
        return SimpleNamespace(mode=RecallMode.DIRECT)

    def pool_texts(self, call_id):
        return ()


class Replies:
    def __init__(self, *, failing=False, texts=("answer",)):
        self.failing, self.texts = failing, texts

    async def generate(self, *args, **kwargs):
        if self.failing:
            raise RuntimeError("private reply should not be logged")
        return tuple(ReplyDraft(text, text, "normal", None) for text in self.texts)


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
    stage._agent = _agent(CallTurnCompletedHandler(Recall(), replies))
    stage._agent._action_router = ActionRouter(
        ((d.ActionKind.SAY, SayHandler("luotianyi", speech, catalog(tmp_path))),)
    )
    return stage, transport, replies, speech


async def turn(stage, text="user"):
    await stage._on_turn(TurnCompleted(CallAudioSemantic(transcript=text)))
    await _eventually(lambda: stage._realize_task is None or stage._realize_task.done())


def acknowledge(stage):
    for response_id, stream_id in tuple(stage._playback.pending_streams):
        if stage._responses[response_id].failed:
            stage.playback_stopped(response_id, stream_id)
        else:
            stage.playback_completed(response_id, stream_id)


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
    acknowledge(stage)
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
    acknowledge(stage)
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
    acknowledge(stage)
    speech.failures = 0
    await turn(stage)
    acknowledge(stage)
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
    acknowledge(stage)
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
            (d.StimulusKind.CALL_TURN_COMPLETED, CallTurnCompletedHandler(Recalling(), replies)),
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
    acknowledge(stage)
    await stage.terminate(CallEndReason.USER_HANGUP)
