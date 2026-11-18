"""Contracts that isolate CallStage from realtime speech vendors."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, TypeAlias
from uuid import UUID

from src.domain.call import CallAudioSemantic
from src.domain.call.omni import AudioFrame as AudioFrame


@dataclass(frozen=True, slots=True)
class RealtimeSpeechConfig:
    language: str | None = None
    instructions: str | None = None


@dataclass(frozen=True, slots=True)
class SpeechStarted:
    item_id: str | None = None


@dataclass(frozen=True, slots=True)
class SpeechStopped:
    item_id: str | None = None


@dataclass(frozen=True, slots=True)
class TranscriptUpdated:
    text: str
    item_id: str


@dataclass(frozen=True, slots=True)
class TurnCompleted:
    semantic: CallAudioSemantic
    item_id: str | None = None
    speech_ended_at: float | None = None
    recognized_at: float | None = None


@dataclass(frozen=True, slots=True)
class TurnInvalid:
    error_code: str
    item_id: str | None = None


@dataclass(frozen=True, slots=True)
class AmbientAudio:
    description: str


@dataclass(frozen=True, slots=True)
class ProviderFailed:
    error_code: str
    retryable: bool


RealtimeSpeechEvent: TypeAlias = (
    SpeechStarted | SpeechStopped | TranscriptUpdated | TurnCompleted | TurnInvalid | AmbientAudio | ProviderFailed
)


class RealtimeSpeechSession(Protocol):
    async def start(self, config: RealtimeSpeechConfig) -> None: ...

    async def push_audio(self, frame: AudioFrame) -> None: ...

    def events(self) -> AsyncIterator[RealtimeSpeechEvent]: ...

    async def wait_failure(self) -> ProviderFailed | None: ...

    async def close(self) -> None: ...


class RealtimeSpeechSessionFactory(Protocol):
    async def create(self, call_id: UUID) -> RealtimeSpeechSession: ...
