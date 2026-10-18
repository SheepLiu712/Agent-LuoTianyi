"""Bounded output ownership; taking a frame does not complete its delivery."""

import asyncio
from uuid import uuid4

from src.domain.agent import SinkRejectedError, SinkRejectionCode

from ..connection import OutboundDelivery


class _Outbox:
    def __init__(self, *, max_outputs: int = 256, max_bytes: int = 16 * 1024 * 1024) -> None:
        self._queue: asyncio.Queue[OutboundDelivery | None] = asyncio.Queue()
        self._pending: dict[str, tuple[asyncio.Future[None], int]] = {}
        self._inflight: set[str] = set()
        self._bytes = 0
        self._max_outputs, self._max_bytes = max_outputs, max_bytes
        self._closed = False

    def enqueue(self, message: str | bytes) -> asyncio.Future[None]:
        if self._closed:
            raise ConnectionError("connection is closed")
        size = len(message.encode("utf-8")) if isinstance(message, str) else len(message)
        if len(self._pending) >= self._max_outputs or self._bytes + size > self._max_bytes:
            raise SinkRejectedError("output queue is full", code=SinkRejectionCode.BACKPRESSURE_TIMEOUT)
        future = asyncio.get_running_loop().create_future()
        future.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        delivery = OutboundDelivery(uuid4().hex, message)
        self._pending[delivery.delivery_id] = (future, size)
        self._bytes += size
        self._queue.put_nowait(delivery)
        return future

    async def next(self) -> OutboundDelivery:
        if self._closed:
            raise ConnectionError("connection is closed")
        delivery = await self._queue.get()
        if delivery is None:
            raise ConnectionError("connection is closed")
        self._inflight.add(delivery.delivery_id)
        return delivery

    def complete(self, delivery_id: str, error: Exception | None = None) -> None:
        if delivery_id not in self._inflight:
            return
        self._inflight.remove(delivery_id)
        self._settle(delivery_id, error)
        if error is not None:
            self.close(error)

    def _settle(self, delivery_id: str, error: Exception | None) -> None:
        future, size = self._pending.pop(delivery_id)
        self._bytes -= size
        if error is None:
            future.set_result(None)
        else:
            future.set_exception(error)

    def close(self, error: Exception | None = None) -> None:
        if self._closed:
            return
        self._closed = True
        error = error or ConnectionError("connection closed before delivery completed")
        for delivery_id in tuple(self._pending):
            self._settle(delivery_id, error)
        self._inflight.clear()
        while not self._queue.empty():
            self._queue.get_nowait()
        self._queue.put_nowait(None)
