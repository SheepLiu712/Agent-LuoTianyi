import pytest
from support.realtime_speech import FakeRealtimeSpeechSession

from src.domain.call import CallAudioSemantic
from src.infrastructure.models.realtime_speech import (
    AudioFrame,
    RealtimeSpeechConfig,
    SpeechStarted,
    TurnCompleted,
)


@pytest.mark.asyncio
async def test_fake_session_is_explicitly_driven_and_records_audio():
    session = FakeRealtimeSpeechSession()
    config = RealtimeSpeechConfig(language="zh-CN")
    frame = AudioFrame(b"\x00\x01", "pcm_s16le", 16_000, 1, sequence=1)
    events = session.events()

    await session.start(config)
    await session.push_audio(frame)
    await session.emit(SpeechStarted())
    await session.emit(TurnCompleted(CallAudioSemantic(transcript="你好")))

    assert session.started_with == config
    assert session.pushed_frames == [frame]
    assert isinstance(await anext(events), SpeechStarted)
    completed = await anext(events)
    assert isinstance(completed, TurnCompleted)
    assert completed.semantic.render() == "用户说：“你好”"
    await session.close()
    with pytest.raises(RuntimeError, match="closed"):
        await session.push_audio(frame)


def test_audio_frame_is_format_metadata_not_a_frozen_wire_layout():
    frame = AudioFrame(b"payload", "provider-neutral", 48_000, 2)
    assert frame.sequence is None
    with pytest.raises(ValueError):
        AudioFrame(b"", "pcm", 16_000, 1)
