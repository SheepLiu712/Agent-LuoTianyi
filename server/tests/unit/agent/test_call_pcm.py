import io
import wave
from contextlib import aclosing
from types import SimpleNamespace

import numpy as np
import pytest
from scipy.signal import resample_poly
from support.skill_support import invocation

import src.domain.agent as d
from src.agent.skills.expression.speaking.call_pcm import (
    StreamingPcmWavDecoder,
    UnsupportedCallAudioError,
    normalize_clip_to_pcm16_mono,
)
from src.agent.skills.expression.speaking.skill import SpeakingSkill
from src.agent.skills.expression.speaking.streaming import AsyncTTS


def _wav(samples: bytes, *, rate: int = 24000, channels: int = 1, width: int = 2) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(width)
        output.setframerate(rate)
        output.writeframes(samples)
    return buffer.getvalue()


def _float_wav() -> bytes:
    fmt = (
        (3).to_bytes(2, "little")
        + (1).to_bytes(2, "little")
        + (24000).to_bytes(4, "little")
        + (96000).to_bytes(4, "little")
        + (4).to_bytes(2, "little")
        + (32).to_bytes(2, "little")
    )
    return b"RIFF" + (40).to_bytes(4, "little") + b"WAVEfmt " + (16).to_bytes(4, "little") + fmt + b"data\0\0\0\0"


def test_decoder_accepts_split_header_unknown_data_and_ancillary_chunks():
    pcm = b"\x01\x00\x02\x00"
    encoded = bytearray(_wav(pcm))
    fmt_end = encoded.index(b"data")
    ancillary = b"JUNK\x03\x00\x00\x00abc\x00" + b"LIST\x02\x00\x00\x00xy"
    encoded[fmt_end:fmt_end] = ancillary
    encoded[4:8] = (0xFFFFFFFF).to_bytes(4, "little")
    data_offset = encoded.index(b"data")
    encoded[data_offset + 4 : data_offset + 8] = (0xFFFFFFFF).to_bytes(4, "little")

    decoder = StreamingPcmWavDecoder()
    output = []
    for byte in encoded:
        output.extend(decoder.feed(bytes((byte,))))
    output.extend(decoder.finish())

    assert b"".join(output) == pcm
    assert decoder.audio_format is not None
    assert decoder.audio_format.sample_rate == 24000


@pytest.mark.parametrize(
    "payload,error",
    [
        (_wav(b"\0" * 8, channels=2), "PCM16 mono"),
        (_wav(b"\0" * 8, width=1), "PCM16 mono"),
        (_float_wav(), "PCM16 mono"),
        (b"RIFF\xff\xff\xff\xffWAVEfmt ", "truncated"),
        (b"not-wave", "RIFF/WAVE"),
    ],
)
def test_decoder_rejects_unsupported_or_truncated_wav(payload, error):
    decoder = StreamingPcmWavDecoder()
    if payload == b"not-wave":
        payload += b"xxxx"
    with pytest.raises(UnsupportedCallAudioError, match=error):
        decoder.feed(payload)
        decoder.finish()


def test_decoder_rejects_oversized_header_and_finish_twice():
    decoder = StreamingPcmWavDecoder(max_header_bytes=16)
    with pytest.raises(UnsupportedCallAudioError, match="64 KiB"):
        decoder.feed(b"RIFF\xff\xff\xff\xffWAVE" + b"x" * 17)

    complete = StreamingPcmWavDecoder()
    complete.feed(_wav(b"\0\0"))
    complete.finish()
    with pytest.raises(RuntimeError, match="only be called once"):
        complete.finish()


@pytest.mark.parametrize("rate", [16000, 32000, 48000])
def test_clip_normalization_matches_one_shot_reference(rate):
    source = np.linspace(-0.8, 0.8, rate // 20, dtype=np.float32)
    actual = normalize_clip_to_pcm16_mono(source, rate)
    expected_samples = resample_poly(source.astype(np.float64), 24000, rate)
    expected = np.rint(np.clip(expected_samples, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    assert actual == expected
    assert len(actual) == len(expected)


def test_clip_normalization_saturates_and_rejects_stereo():
    output = np.frombuffer(normalize_clip_to_pcm16_mono(np.array([-2.0, 2.0]), 24000), dtype="<i2")
    assert output.tolist() == [-32767, 32767]
    with pytest.raises(UnsupportedCallAudioError, match="mono"):
        normalize_clip_to_pcm16_mono(np.zeros((2, 2)), 24000)


@pytest.mark.asyncio
async def test_backend_without_verified_call_pcm_fails_explicitly():
    module = SimpleNamespace(
        stream_synthesize_speech_with_tone=lambda *_args, **_kwargs: iter((b"RIFF",)),
    )
    stream = AsyncTTS(SimpleNamespace(tts_module={"luotianyi": module})).stream(
        character_id="luotianyi",
        text="文字",
        tone="normal",
        cancellation=d.CancellationToken(),
        output_format=d.CALL_PCM_FORMAT,
    )
    async with aclosing(stream):
        with pytest.raises(UnsupportedCallAudioError, match="does not support verified CALL PCM"):
            await anext(stream)


class _PcmEngine:
    def __init__(self, chunks):
        self.chunks = chunks

    async def stream(self, **_kwargs):
        for chunk in self.chunks:
            yield chunk


@pytest.mark.asyncio
async def test_speaking_splits_large_call_clip_into_bounded_even_chunks():
    data = bytes(range(256)) * 129  # 33024 bytes, not a multiple of the 16 KiB limit
    skill = SpeakingSkill({}, _PcmEngine((data,)))

    chunks = [
        chunk
        async for chunk in skill.speak(
            invocation(), text="文字", tone=d.Tone(value="normal"), output_format=d.CALL_PCM_FORMAT
        )
    ]

    assert [len(chunk.data) for chunk in chunks] == [16384, 16384, 256]
    assert b"".join(chunk.data for chunk in chunks) == data
    assert all(len(chunk.data) % 2 == 0 for chunk in chunks)
    assert all(chunk.audio_format == d.CALL_PCM_FORMAT for chunk in chunks)


@pytest.mark.asyncio
async def test_speaking_rejects_odd_call_pcm_without_dropping_tail():
    skill = SpeakingSkill({}, _PcmEngine((b"odd",)))
    with pytest.raises(ValueError, match="PCM16"):
        _ = [
            chunk
            async for chunk in skill.speak(
                invocation(), text="文字", tone=d.Tone(value="normal"), output_format=d.CALL_PCM_FORMAT
            )
        ]
