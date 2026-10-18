"""Chat connection state without any physical WebSocket dependency."""

import asyncio
import json
import time

from ._outbox import _Outbox


class _ChatPeer:
    def __init__(self, user_id: str, connection_id: object, capabilities, config) -> None:
        self.user_uuid = user_id
        self.connection_id = connection_id
        self.capabilities = frozenset(capabilities)
        self.client_mode: dict = {"types": []}
        self.last_ping_id: int | None = None
        self.outbox = _Outbox(max_outputs=config.max_outputs, max_bytes=config.max_bytes)
        self.is_closed = False
        self._business_ready = asyncio.Event()

    def mark_disconnected(self) -> None:
        self.is_closed = True
        self.outbox.close()
        self._business_ready.set()

    def _release_business_outputs(self) -> None:
        self._business_ready.set()

    def enqueue_event(self, event_type: str, payload: dict, *, reply_to=None):
        event = {"type": event_type, "ts": int(time.time() * 1000), "payload": payload}
        if reply_to:
            event["reply_to"] = reply_to
        return self.outbox.enqueue(json.dumps(event, ensure_ascii=False))

    async def send_event(self, event_type: str, payload: dict) -> None:
        await self._business_ready.wait()
        await asyncio.shield(self.enqueue_event(event_type, payload))

    async def send_json(self, event: dict) -> None:
        await self._business_ready.wait()
        await asyncio.shield(self.outbox.enqueue(json.dumps(event, ensure_ascii=False)))
