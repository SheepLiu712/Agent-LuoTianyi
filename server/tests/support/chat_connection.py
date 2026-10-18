"""In-memory peer for Stage/Adapter unit fixtures; production network paths use adapter handles."""

import asyncio
import json


from src.adapter.websocket.chat._binding import Binding
from src.adapter.websocket.chat._delivery import DeliveryConfig


class StubChatConnection(Binding):
    def __init__(self, websocket, user_uuid: str | None, user_name: str | None, *, config=None):
        super().__init__(user_uuid, object(), (), config or DeliveryConfig())
        self.websocket = websocket
        self.user_uuid = user_uuid
        self.user_name = user_name
        self.last_ping_id: int | None = None
        self.client_mode: dict = {"types": []}
        self.capabilities: set[str] = set()
        self._send_lock = asyncio.Lock()
        self.is_closed = False

    async def send(self, message: str) -> None:
        async with self._send_lock:
            if self.is_closed:
                raise ConnectionError("connection is closed")
            try:
                await asyncio.wait_for(self.websocket.send_json(json.loads(message)), timeout=10.0)
            except BaseException:
                self.is_closed = True
                raise

    def set_user(self, user_uuid: str, user_name: str):
        self.user_uuid = user_uuid
        self.user_name = user_name
