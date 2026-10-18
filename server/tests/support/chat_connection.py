"""In-memory peer for Stage/Adapter unit fixtures; production network paths use adapter handles."""

import asyncio
import time
from typing import Any


class StubChatConnection:
    def __init__(self, websocket, user_uuid: str | None, user_name: str | None):
        self.websocket = websocket
        self.user_uuid = user_uuid
        self.user_name = user_name
        self.last_ping_id: int | None = None
        self.client_mode: dict = {"types": []}
        self.capabilities: set[str] = set()
        self._send_lock = asyncio.Lock()
        self._closed = False

    @property
    def is_closed(self) -> bool:
        """返回本连接是否已断开或发送失败；旧连接不会自动关联到重连后的 socket。"""
        return self._closed

    async def send_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """将 event_type 和 payload 封装为事件并串行发送；单包限时十秒，失败抛出且不重试。"""
        async with self._send_lock:
            if self._closed:
                raise ConnectionError("WebSocket connection is closed")
            try:
                await asyncio.wait_for(
                    self.websocket.send_json(
                        {
                            "type": event_type,
                            "ts": int(time.time() * 1000),
                            "payload": payload,
                        }
                    ),
                    timeout=10.0,
                )
            except BaseException:
                # 发送被中断时交付结果也不确定，禁止继续使用这条连接发送。
                self._closed = True
                raise

    def mark_disconnected(self) -> None:
        """由连接接入层标记断开，使旧连接上的业务输出立即失效。"""
        self._closed = True

    def set_user(self, user_uuid: str, user_name: str):
        self.user_uuid = user_uuid
        self.user_name = user_name
