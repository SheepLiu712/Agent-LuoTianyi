"""Offline WebSocket double for the Aliyun realtime speech adapter."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from websockets.exceptions import ConnectionClosedError
from websockets.frames import Close

_CLOSED = object()


class FakeAliyunWebSocket:
    def __init__(
        self,
        *,
        block_sends: bool = False,
        acknowledge_session: bool = True,
        block_close: bool = False,
        fail_send_type: str | None = None,
    ) -> None:
        self.sent: list[dict[str, Any]] = []
        self.incoming: asyncio.Queue[str | bytes | object] = asyncio.Queue()
        self.closed = False
        self.send_started = asyncio.Event()
        self.release_sends = asyncio.Event()
        self.acknowledge_session = acknowledge_session
        self.block_close = block_close
        self.fail_send_type = fail_send_type
        self.close_started = asyncio.Event()
        if not block_sends:
            self.release_sends.set()

    async def send(self, message: str) -> None:
        self.send_started.set()
        await self.release_sends.wait()
        value = json.loads(message)
        if value.get("type") == self.fail_send_type:
            raise RuntimeError("offline fake send failure")
        self.sent.append(value)
        if value.get("type") == "session.update" and self.acknowledge_session:
            await self.server_event({"type": "session.updated"})

    async def recv(self) -> str | bytes:
        value = await self.incoming.get()
        if value is _CLOSED:
            raise ConnectionClosedError(Close(1011, "offline fake failure"), None)
        return value  # type: ignore[return-value]

    async def close(self) -> None:
        self.close_started.set()
        if self.block_close:
            await asyncio.Future()
        self.closed = True

    async def server_event(self, value: dict[str, Any]) -> None:
        await self.incoming.put(json.dumps(value))

    async def abnormal_close(self) -> None:
        await self.incoming.put(_CLOSED)


class FakeAliyunConnector:
    def __init__(self, *sockets: FakeAliyunWebSocket) -> None:
        self.sockets = list(sockets)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, url: str, **kwargs: Any) -> FakeAliyunWebSocket:
        self.calls.append((url, kwargs))
        return self.sockets.pop(0)
