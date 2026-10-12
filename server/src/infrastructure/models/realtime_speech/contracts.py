"""Contracts that isolate CallStage from realtime speech vendors."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, TypeAlias
from uuid import UUID

from src.domain.call import CallAudioSemantic


@dataclass(frozen=True, slots=True)
class RealtimeSpeechConfig:
    language: str | None = None


@dataclass(frozen=True, slots=True)
class AudioFrame:
    payload: bytes
    encoding: str
    sample_rate: int
    channels: int
    sequence: int | None = None

    def __post_init__(self) -> None:
        if not self.payload:
            raise ValueError("audio frame payload cannot be empty")
        if not self.encoding:
            raise ValueError("audio frame encoding is required")
        if self.sample_rate <= 0 or self.channels <= 0:
            raise ValueError("sample_rate and channels must be positive")
        if self.sequence is not None and self.sequence < 0:
            raise ValueError("sequence cannot be negative")


@dataclass(frozen=True, slots=True)
class SpeechStarted:
    pass


@dataclass(frozen=True, slots=True)
class SpeechStopped:
    pass


@dataclass(frozen=True, slots=True)
class TurnCompleted:
    semantic: CallAudioSemantic


@dataclass(frozen=True, slots=True)
class TurnInvalid:
    error_code: str


@dataclass(frozen=True, slots=True)
class AmbientAudio:
    description: str


@dataclass(frozen=True, slots=True)
class ProviderFailed:
    error_code: str
    retryable: bool


RealtimeSpeechEvent: TypeAlias = (
    SpeechStarted | SpeechStopped | TurnCompleted | TurnInvalid | AmbientAudio | ProviderFailed
)


class RealtimeSpeechSession(Protocol):
    async def start(self, config: RealtimeSpeechConfig) -> None: ...

    async def push_audio(self, frame: AudioFrame) -> None: ...

    def events(self) -> AsyncIterator[RealtimeSpeechEvent]: ...

    async def close(self) -> None: ...


class RealtimeSpeechSessionFactory(Protocol):
    async def create(self, call_id: UUID) -> RealtimeSpeechSession: ...
