"""单次通话连接的权限和发送队列；不持有跨连接协议状态。"""

from __future__ import annotations

import asyncio
from uuid import uuid4

from src.domain.agent import SinkRejectedError, SinkRejectionCode

from ..connection import OutboundDelivery
from .errors import CallTransportError


class Binding:
    """关联唯一 Session，失效后不能被恢复或影响后续连接。"""

    def __init__(self, session, *, connection_id: object):
        self.session = session
        self.connection_id = connection_id
        self._outbox = _Outbox(max_outputs=512, max_bytes=8 * 1024 * 1024)
        self.is_closed = False
        self.is_ready = False

    async def receive(self, frame) -> None:
        """仅允许有效连接向关联会话投递。"""
        self._require_open()
        await self.session.receive(self, frame)

    def enqueue(self, message: str | bytes) -> None:
        """接纳本连接的网络发送任务，容量不足时明确拒绝。"""
        self._require_open()
        self._outbox._enqueue(message)

    async def next_output(self) -> OutboundDelivery:
        """等待下一次发送任务，断线唤醒且不消费新连接的队列。"""
        self._require_open()
        return await self._outbox._next()

    def complete_output(self, delivery_id: str, *, error: Exception | None = None) -> None:
        """完成一次网络发送；不推进协议 ACK 游标。"""
        if self.is_closed:
            return
        self._outbox._complete(delivery_id, error)
        if error is not None:
            self.invalidate()

    def invalidate(self) -> None:
        """永久撤销连接权限，清理发送任务并唤醒等待者。"""
        self.is_closed = True
        self._outbox._close()

    async def drain(self) -> None:
        """等待已接纳网络任务完成，用于有限的终态投递。"""
        await self._outbox._idle.wait()

    def _require_open(self):
        if self.is_closed:
            raise CallTransportError("STALE_CALL_CONNECTION", close_code=1008)


class _Outbox:
    """保存本连接的编码报文与在途字节数，支持有限排空。"""

    def __init__(self, *, max_outputs: int = 256, max_bytes: int = 16 * 1024 * 1024) -> None:
        self._queue: asyncio.Queue[OutboundDelivery | None] = asyncio.Queue()
        self._pending: dict[str, int] = {}
        self._inflight: set[str] = set()
        self._bytes = 0
        self._max_outputs, self._max_bytes = max_outputs, max_bytes
        self._closed = False
        self._idle = asyncio.Event()
        self._idle.set()

    def _enqueue(self, message: str | bytes) -> None:
        if self._closed:
            raise ConnectionError("connection is closed")
        size = len(message.encode("utf-8")) if isinstance(message, str) else len(message)
        if len(self._pending) >= self._max_outputs or self._bytes + size > self._max_bytes:
            raise SinkRejectedError("output queue is full", code=SinkRejectionCode.BACKPRESSURE_TIMEOUT)
        delivery = OutboundDelivery(uuid4().hex, message)
        self._pending[delivery.delivery_id] = size
        self._bytes += size
        self._idle.clear()
        self._queue.put_nowait(delivery)

    async def _next(self) -> OutboundDelivery:
        """取出一个报文并标记在途；取出不代表发送完成，关闭时抛出连接错误。"""
        if self._closed:
            raise ConnectionError("connection is closed")
        delivery = await self._queue.get()
        if delivery is None:
            raise ConnectionError("connection is closed")
        self._inflight.add(delivery.delivery_id)
        return delivery

    def _complete(self, delivery_id: str, error: Exception | None = None) -> None:
        """记录指定投递的网络结果；发送失败时关闭整个队列。"""
        if delivery_id not in self._inflight:
            return
        self._inflight.remove(delivery_id)
        self._settle(delivery_id)
        if error is not None:
            self._close()

    def _settle(self, delivery_id: str) -> None:
        size = self._pending.pop(delivery_id)
        self._bytes -= size
        if not self._pending:
            self._idle.set()

    def _close(self) -> None:
        """关闭队列，使未完成投递失败，并唤醒等待取报文的发送循环。"""
        if self._closed:
            return
        self._closed = True
        for delivery_id in tuple(self._pending):
            self._settle(delivery_id)
        self._inflight.clear()
        while not self._queue.empty():
            self._queue.get_nowait()
        self._queue.put_nowait(None)
