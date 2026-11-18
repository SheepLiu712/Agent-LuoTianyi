"""Explicitly driven realtime speech fake for unit and integration tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from uuid import UUID

from src.infrastructure.models.realtime_speech import (
    AudioFrame,
    ProviderFailed,
    RealtimeSpeechConfig,
    RealtimeSpeechEvent,
    RealtimeSpeechSession,
)


class FakeRealtimeSpeechSession:
    def __init__(self) -> None:
        self.started_with: RealtimeSpeechConfig | None = None
        self.pushed_frames: list[AudioFrame] = []
        self.closed = False
        self._events: asyncio.Queue[RealtimeSpeechEvent | None] = asyncio.Queue()
        self._terminal = asyncio.Event()
        self._failure: ProviderFailed | None = None

    async def start(self, config: RealtimeSpeechConfig) -> None:
        if self.closed:
            raise RuntimeError("session is closed")
        self.started_with = config

    async def push_audio(self, frame: AudioFrame) -> None:
        if self.closed:
            raise RuntimeError("session is closed")
        self.pushed_frames.append(frame)

    async def emit(self, event: RealtimeSpeechEvent) -> None:
        if self.closed:
            raise RuntimeError("session is closed")
        if isinstance(event, ProviderFailed):
            self._failure = event
            self._terminal.set()
        await self._events.put(event)

    async def events(self) -> AsyncIterator[RealtimeSpeechEvent]:
        while True:
            event = await self._events.get()
            if event is None:
                return
            yield event

    async def wait_failure(self) -> ProviderFailed | None:
        await self._terminal.wait()
        return self._failure

    async def close(self) -> None:
        if not self.closed:
            self.closed = True
            self._terminal.set()
            await self._events.put(None)

    def pushed_evidence(self) -> list[dict[str, object]]:
        return [{"payload_hex": frame.payload.hex(), "sequence": frame.sequence} for frame in self.pushed_frames]


class FakeRealtimeSpeechSessionFactory:
    def __init__(self) -> None:
        self.sessions: dict[UUID, FakeRealtimeSpeechSession] = {}

    @property
    def is_configured(self) -> bool:
        return True

    async def create(self, call_id: UUID) -> RealtimeSpeechSession:
        session = FakeRealtimeSpeechSession()
        self.sessions[call_id] = session
        return session

    def evidence(self) -> list[dict[str, object]]:
        return [
            {
                "call_id": str(call_id),
                "frames": [
                    {
                        "payload": frame.payload.hex(),
                        "sequence": frame.sequence,
                        "encoding": frame.encoding,
                        "sample_rate": frame.sample_rate,
                        "channels": frame.channels,
                    }
                    for frame in session.pushed_frames
                ],
            }
            for call_id, session in self.sessions.items()
        ]
