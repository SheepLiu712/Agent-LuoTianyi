"""Explicitly driven realtime speech fake for unit and integration tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from uuid import UUID

from src.infrastructure.models.realtime_speech import (
    AudioFrame,
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
        await self._events.put(event)

    async def events(self) -> AsyncIterator[RealtimeSpeechEvent]:
        while True:
            event = await self._events.get()
            if event is None:
                return
            yield event

    async def close(self) -> None:
        if not self.closed:
            self.closed = True
            await self._events.put(None)


class FakeRealtimeSpeechSessionFactory:
    def __init__(self) -> None:
        self.sessions: dict[UUID, FakeRealtimeSpeechSession] = {}

    async def create(self, call_id: UUID) -> RealtimeSpeechSession:
        session = FakeRealtimeSpeechSession()
        self.sessions[call_id] = session
        return session
