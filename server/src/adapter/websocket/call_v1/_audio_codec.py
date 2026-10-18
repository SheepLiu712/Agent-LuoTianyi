"""Pure ``call.v1`` binary PCM16 audio-frame codec.

This module intentionally owns only wire representation validation. Session
registration, direction, sequencing windows, replay handling, and WebSocket
close-code selection belong to later Adapter and transport layers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

HEADER_SIZE = 15
VERSION = 1
CHAT_ROUTE = 1
CALL_ROUTE = 2
FINAL_FLAG = 1
ALLOWED_FLAGS_MASK = FINAL_FLAG
UINT32_MAX = (1 << 32) - 1
MAX_PAYLOAD_BYTES = 16_384


class _AudioFrameCodecError(ValueError):
    """A codec validation failure with a stable cross-client error code."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        self.message = message or code
        super().__init__(self.message)


@dataclass(frozen=True, slots=True)
class _WireAudioFrame:
    """The adapter-layer representation of one PCM16 mono audio frame."""

    version: int
    route: int
    flags: int
    stream_id: int
    seq: int
    payload: bytes


@runtime_checkable
class _AudioFrameCodec(Protocol):
    """A replaceable encoding for a single call audio frame."""

    def encode(self, frame: _WireAudioFrame) -> bytes:
        """Encode one wire frame."""

    def decode(self, encoded: bytes) -> _WireAudioFrame:
        """Decode one wire frame."""


class _BinaryAudioFrameCodec:
    """Strict codec for the fixed-layout ``call.v1`` binary audio frame."""

    def encode(self, frame: _WireAudioFrame) -> bytes:
        if not isinstance(frame, _WireAudioFrame):
            raise _AudioFrameCodecError("INVALID_FIELD_TYPE")

        self._validate_frame(frame)
        payload_length = len(frame.payload)
        return b"".join(
            (
                bytes((frame.version, frame.route, frame.flags)),
                frame.stream_id.to_bytes(4, byteorder="big"),
                frame.seq.to_bytes(4, byteorder="big"),
                payload_length.to_bytes(4, byteorder="big"),
                frame.payload,
            )
        )

    def decode(self, encoded: bytes) -> _WireAudioFrame:
        if type(encoded) is not bytes:
            raise _AudioFrameCodecError("INVALID_FIELD_TYPE")
        if len(encoded) < HEADER_SIZE:
            raise _AudioFrameCodecError("HEADER_TRUNCATED")

        version = encoded[0]
        route = encoded[1]
        flags = encoded[2]
        stream_id = int.from_bytes(encoded[3:7], byteorder="big")
        seq = int.from_bytes(encoded[7:11], byteorder="big")
        payload_length = int.from_bytes(encoded[11:15], byteorder="big")
        actual_payload_length = len(encoded) - HEADER_SIZE

        if version != VERSION:
            raise _AudioFrameCodecError("UNSUPPORTED_VERSION")
        if route not in (CHAT_ROUTE, CALL_ROUTE):
            raise _AudioFrameCodecError("INVALID_ROUTE")
        if flags & ~ALLOWED_FLAGS_MASK:
            raise _AudioFrameCodecError("UNSUPPORTED_FLAGS")
        if seq == 0:
            raise _AudioFrameCodecError("INVALID_SEQ")
        if payload_length != actual_payload_length:
            raise _AudioFrameCodecError("PAYLOAD_LENGTH_MISMATCH")
        self._validate_payload_length(actual_payload_length)
        payload = self._copy_payload(encoded)
        return _WireAudioFrame(version, route, flags, stream_id, seq, payload)

    @staticmethod
    def _validate_frame(frame: _WireAudioFrame) -> None:
        if (
            any(
                type(value) is not int
                for value in (frame.version, frame.route, frame.flags, frame.stream_id, frame.seq)
            )
            or type(frame.payload) is not bytes
        ):
            raise _AudioFrameCodecError("INVALID_FIELD_TYPE")
        if not 0 <= frame.version <= 0xFF or not 0 <= frame.route <= 0xFF or not 0 <= frame.flags <= 0xFF:
            raise _AudioFrameCodecError("FIELD_OUT_OF_RANGE")
        if not 0 <= frame.stream_id <= UINT32_MAX or not 0 <= frame.seq <= UINT32_MAX:
            raise _AudioFrameCodecError("FIELD_OUT_OF_RANGE")
        if frame.version != VERSION:
            raise _AudioFrameCodecError("UNSUPPORTED_VERSION")
        if frame.route not in (CHAT_ROUTE, CALL_ROUTE):
            raise _AudioFrameCodecError("INVALID_ROUTE")
        if frame.flags & ~ALLOWED_FLAGS_MASK:
            raise _AudioFrameCodecError("UNSUPPORTED_FLAGS")
        if frame.seq == 0:
            raise _AudioFrameCodecError("INVALID_SEQ")
        _BinaryAudioFrameCodec._validate_payload(frame.payload)

    @staticmethod
    def _validate_payload(payload: bytes) -> None:
        _BinaryAudioFrameCodec._validate_payload_length(len(payload))

    @staticmethod
    def _validate_payload_length(payload_length: int) -> None:
        if payload_length > MAX_PAYLOAD_BYTES:
            raise _AudioFrameCodecError("PAYLOAD_TOO_LARGE")
        if payload_length == 0:
            raise _AudioFrameCodecError("EMPTY_PAYLOAD")
        if payload_length % 2:
            raise _AudioFrameCodecError("PCM_ALIGNMENT_ERROR")

    @staticmethod
    def _copy_payload(encoded: bytes) -> bytes:
        return encoded[HEADER_SIZE:]
