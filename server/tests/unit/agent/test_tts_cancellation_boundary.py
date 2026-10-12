"""Lock the cancellation boundaries between TTS reads and output delivery."""

import asyncio
from contextlib import aclosing
from types import SimpleNamespace

import pytest

import src.domain.agent as d
from src.agent.handlers.action.say import SayHandler
from src.agent.skills.expression.speaking.errors import TTSStreamCancelled
from src.agent.skills.expression.speaking.streaming import AsyncTTS


class _ResultCancellingTask(asyncio.Future):
    """A completed pending read that publishes cancellation from result()."""

    def __init__(self, cancellation: d.CancellationToken, result: object) -> None:
        super().__init__()
        self._cancellation = cancellation
        self.set_result(result)

    def result(self) -> object:
        self._cancellation.cancel(d.CancellationReason.NO_LONGER_NEEDED)
        return super().result()


class _RecordingOutputs:
    def __init__(self) -> None:
        self.drafts = []

    async def emit(self, draft):
        self.drafts.append(draft)


def _say_action() -> d.Say:
    return d.Say(
        action_id="say",
        content="显示文字",
        sound_content="朗读文字",
        prepared_audio_ref=None,
        tone=d.Tone(value="normal"),
        expression=None,
        delivery=d.OutputDelivery.CONVERSATION,
    )


def _execution_context(cancellation: d.CancellationToken) -> d.ExecutionContext:
    return d.ExecutionContext(
        execution_id="execution",
        interaction_id="interaction",
        current_interaction_revision=1,
        cancellation=cancellation,
    )


@pytest.mark.asyncio
async def test_async_tts_does_not_yield_chunk_when_read_result_observes_cancellation(monkeypatch):
    cancellation = d.CancellationToken()
    module = SimpleNamespace(
        stream_synthesize_speech_with_tone=lambda *_args, **_kwargs: iter((b"audio",)),
    )

    original_create_task = asyncio.create_task
    reads = 0

    def completed_read(awaitable):
        nonlocal reads
        reads += 1
        if reads != 1:
            return original_create_task(awaitable)
        awaitable.close()
        return _ResultCancellingTask(cancellation, b"audio")

    monkeypatch.setattr(asyncio, "create_task", completed_read)
    tts = AsyncTTS(SimpleNamespace(tts_module={"luotianyi": module}))

    async with aclosing(
        tts.stream(character_id="luotianyi", text="文字", tone="normal", cancellation=cancellation)
    ) as stream:
        with pytest.raises(TTSStreamCancelled):
            await anext(stream)


@pytest.mark.asyncio
async def test_say_does_not_emit_chunk_when_stream_yield_observes_cancellation():
    cancellation = d.CancellationToken()

    class CancellingSpeaking:
        async def speak(self, *_args, **_kwargs):
            cancellation.cancel(d.CancellationReason.NO_LONGER_NEEDED)
            yield SimpleNamespace(data=b"audio", framing=d.AudioFraming.FILE_FRAGMENT)

    outputs = _RecordingOutputs()
    handler = SayHandler("luotianyi", CancellingSpeaking(), prepared_speech=None)

    result = await handler.realize(_say_action(), _execution_context(cancellation), outputs)

    assert result.status is d.ActionExecutionStatus.CANCELLED
    assert result.error_code is d.ExecutionErrorCode.CANCELLED
    assert not any(type(draft).__name__ == "AudioChunkDraft" for draft in outputs.drafts)
    assert not any(type(draft).__name__ == "MessageEndDraft" for draft in outputs.drafts)
