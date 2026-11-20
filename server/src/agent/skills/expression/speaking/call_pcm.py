"""CALL TTS 的有限 WAV 解析与 24 kHz PCM16 单声道规范化。"""

from __future__ import annotations

import math
from dataclasses import dataclass

CALL_SAMPLE_RATE = 24000
MAX_WAV_HEADER_BYTES = 64 * 1024


class UnsupportedCallAudioError(RuntimeError):
    """TTS 后端不能证明能够产生 CALL 所需的音频格式。"""


@dataclass(frozen=True, slots=True)
class WavFormat:
    encoding_code: int
    channels: int
    sample_rate: int
    bits_per_sample: int


class StreamingPcmWavDecoder:
    """解析分块 RIFF/WAVE，并只在完整验证 fmt 后返回 data payload。"""

    def __init__(self, *, max_header_bytes: int = MAX_WAV_HEADER_BYTES) -> None:
        self._buffer = bytearray()
        self._format: WavFormat | None = None
        self._data_remaining: int | None = None
        self._unknown_data = False
        self._finished = False
        self._max_header_bytes = max_header_bytes

    @property
    def audio_format(self) -> WavFormat | None:
        return self._format

    def feed(self, chunk: bytes) -> tuple[bytes, ...]:
        if self._finished:
            raise RuntimeError("WAV decoder is already finished")
        if not isinstance(chunk, bytes):
            raise TypeError("WAV chunk must be bytes")
        if chunk:
            self._buffer.extend(chunk)
        if self._unknown_data:
            return self._drain_unknown_data()
        if self._data_remaining is not None:
            return self._drain_known_data()
        self._parse_header()
        if self._unknown_data:
            return self._drain_unknown_data()
        if self._data_remaining is not None:
            return self._drain_known_data()
        return ()

    def finish(self) -> tuple[bytes, ...]:
        if self._finished:
            raise RuntimeError("WAV decoder finish may only be called once")
        self._finished = True
        if self._unknown_data:
            return self._drain_unknown_data()
        if self._data_remaining is None:
            raise UnsupportedCallAudioError("WAV data chunk is missing or header is truncated")
        output = self._drain_known_data()
        if self._data_remaining != 0:
            raise UnsupportedCallAudioError("WAV data chunk is truncated")
        if self._buffer:
            raise UnsupportedCallAudioError("WAV contains bytes after the declared data chunk")
        return output

    def _parse_header(self) -> None:
        if len(self._buffer) < 12:
            self._check_header_limit()
            return
        if self._buffer[:4] != b"RIFF" or self._buffer[8:12] != b"WAVE":
            raise UnsupportedCallAudioError("TTS stream is not RIFF/WAVE")
        offset = 12
        while len(self._buffer) >= offset + 8:
            chunk_id = bytes(self._buffer[offset : offset + 4])
            chunk_size = int.from_bytes(self._buffer[offset + 4 : offset + 8], "little")
            payload_start = offset + 8
            if chunk_id == b"data":
                if self._format is None:
                    raise UnsupportedCallAudioError("WAV data precedes fmt")
                del self._buffer[:payload_start]
                if chunk_size == 0xFFFFFFFF:
                    self._unknown_data = True
                else:
                    self._data_remaining = chunk_size
                return
            padded_end = payload_start + chunk_size + (chunk_size % 2)
            if len(self._buffer) < padded_end:
                self._check_header_limit()
                return
            if chunk_id == b"fmt ":
                self._read_format(bytes(self._buffer[payload_start : payload_start + chunk_size]))
            offset = padded_end
            self._check_header_limit(offset)
        self._check_header_limit()

    def _read_format(self, payload: bytes) -> None:
        if len(payload) < 16:
            raise UnsupportedCallAudioError("WAV fmt chunk is truncated")
        audio_format = WavFormat(
            encoding_code=int.from_bytes(payload[0:2], "little"),
            channels=int.from_bytes(payload[2:4], "little"),
            sample_rate=int.from_bytes(payload[4:8], "little"),
            bits_per_sample=int.from_bytes(payload[14:16], "little"),
        )
        if audio_format.encoding_code != 1 or audio_format.bits_per_sample != 16 or audio_format.channels != 1:
            raise UnsupportedCallAudioError("CALL TTS requires PCM16 mono WAV")
        if audio_format.sample_rate <= 0:
            raise UnsupportedCallAudioError("WAV sample rate is invalid")
        self._format = audio_format

    def _drain_unknown_data(self) -> tuple[bytes, ...]:
        if not self._buffer:
            return ()
        data = bytes(self._buffer)
        self._buffer.clear()
        return (data,)

    def _drain_known_data(self) -> tuple[bytes, ...]:
        assert self._data_remaining is not None
        size = min(len(self._buffer), self._data_remaining)
        if size == 0:
            return ()
        data = bytes(self._buffer[:size])
        del self._buffer[:size]
        self._data_remaining -= size
        return (data,)

    def _check_header_limit(self, examined: int | None = None) -> None:
        if (examined if examined is not None else len(self._buffer)) > self._max_header_bytes:
            raise UnsupportedCallAudioError("WAV header exceeds 64 KiB")


def normalize_clip_to_pcm16_mono(audio_data, sample_rate: int) -> bytes:
    """在完整 TTS clip 边界将单声道样本重采样并饱和量化为 24 kHz PCM16。"""
    import numpy as np
    from scipy.signal import resample_poly

    samples = np.asarray(audio_data)
    if samples.ndim != 1:
        raise UnsupportedCallAudioError("CALL TTS requires mono clips")
    if sample_rate <= 0:
        raise UnsupportedCallAudioError("TTS clip sample rate is invalid")
    samples = samples.astype(np.float64, copy=False)
    if sample_rate != CALL_SAMPLE_RATE:
        divisor = math.gcd(sample_rate, CALL_SAMPLE_RATE)
        samples = resample_poly(samples, CALL_SAMPLE_RATE // divisor, sample_rate // divisor)
    samples = np.clip(samples, -1.0, 1.0)
    return np.rint(samples * 32767.0).astype("<i2").tobytes()
