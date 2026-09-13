"""按真实连接串行投递完整消息；跨消息保持播放终止位置。"""
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
import json
from uuid import NAMESPACE_URL, uuid5

import src.domain.agent as d
from src.system.user_interface.types import ChatResponse
from src.system.user_interface.websocket_service import WebSocketConnection
from src.utils.logger import get_logger
from ._protocol import payloads


@dataclass(frozen=True)
class _DeliveryConfig:
    max_outputs: int = 256
    max_bytes: int = 16 * 1024 * 1024
    max_messages: int = 64

    @classmethod
    def from_dict(cls, config: dict) -> _DeliveryConfig:
        if not isinstance(config, dict):
            raise TypeError("adapter config must be a dictionary")
        values = {key: config.get(key, default) for key, default in
                  (("max_outputs", 256), ("max_bytes", 16 * 1024 * 1024), ("max_messages", 64))}
        if any(type(value) is not int or value <= 0 for value in values.values()):
            raise ValueError("adapter queue limits must be positive integers")
        return cls(**values)


def completion(label: str) -> asyncio.Future[None]:
    future = asyncio.get_running_loop().create_future()

    def observe(result: asyncio.Future[None]) -> None:
        if not result.cancelled() and result.exception() is not None:
            get_logger(__name__).error("WebSocket delivery failed %s: %s", label, result.exception())

    future.add_done_callback(observe)
    return future


@dataclass
class _Item:
    output: d.AgentOutput
    future: asyncio.Future[None]
    size: int


@dataclass
class _Message:
    key: tuple[str, str, str]
    delivery: d.OutputDelivery
    done: asyncio.Future[None]
    items: deque[_Item] = field(default_factory=deque)
    accepted_end: bool = False
    cancelled: bool = False
    started: bool = False
    ended: bool = False
    sequence: int = 0
    current: _Item | None = None


class _ConnectionDelivery:
    def __init__(self, connection: WebSocketConnection, config: _DeliveryConfig) -> None:
        self.connection, self.config = connection, config
        self.messages: deque[_Message] = deque()
        self.by_key: dict[tuple[str, str, str], _Message] = {}
        self.pending_outputs = 0
        self.pending_bytes = 0
        self.changed = asyncio.Event()
        self.task: asyncio.Task[None] | None = None
        self.closed = False

    def submit(self, output: d.AgentOutput) -> asyncio.Future[None]:
        if self.closed or self.connection.is_closed:
            raise d.SinkRejectedError("connection is closed", code=d.SinkRejectionCode.SINK_CLOSED)
        key = (output.interaction_id, output.execution_id, output.action_id)
        message = self.by_key.get(key)
        if message is not None and (message.accepted_end or message.cancelled or message.delivery != output.delivery):
            raise d.SinkRejectedError("message already ended or delivery changed", code=d.SinkRejectionCode.CONTENT_CONFLICT)
        size = len(output.data) if isinstance(output, d.AudioChunkOutput) else len(str(output).encode("utf-8"))
        if (self.pending_outputs >= self.config.max_outputs or self.pending_bytes + size > self.config.max_bytes
                or (message is None and len(self.messages) >= self.config.max_messages)):
            raise d.SinkRejectedError("connection output queue is full", code=d.SinkRejectionCode.BACKPRESSURE_TIMEOUT)
        if message is None:
            message = _Message(key, output.delivery, completion(f"message={key}"))
            self.messages.append(message)
            self.by_key[key] = message
        future = completion(f"interaction={key[0]} execution={key[1]} sequence={output.sequence_no}")
        message.items.append(_Item(output, future, size))
        message.accepted_end = isinstance(output, d.MessageEndOutput)
        self.pending_outputs += 1
        self.pending_bytes += size
        self.changed.set()
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._run(), name="websocket-output")
        return future

    def cancel(self, interaction_id: str, execution_id: str | None = None) -> list[asyncio.Future[None]]:
        done = []
        for message in list(self.messages):
            if message.key[0] != interaction_id or (execution_id is not None and message.key[1] != execution_id):
                continue
            message.cancelled = True
            done.append(message.done)
            if message.current is not None:
                message.current.future.cancel()
            while message.items:
                item = message.items.popleft()
                item.future.cancel()
                self._release(item)
            # 未开始的排队消息可立即清理，不能等其他交互的慢消息结束。
            if not message.started and message.current is None:
                self._finish(message)
        self.changed.set()
        return done

    def disconnect(self) -> None:
        self.closed = True
        self.connection.mark_disconnected()
        error = ConnectionError("WebSocket connection disconnected")
        for message in list(self.messages):
            if message.current is not None and not message.current.future.done():
                message.current.future.set_exception(error)
            self._finish(message, error)
        self.changed.set()

    def _release(self, item: _Item) -> None:
        self.pending_outputs -= 1
        self.pending_bytes -= item.size

    def _finish(self, message: _Message, error: Exception | None = None) -> None:
        while message.items:
            item = message.items.popleft()
            if not item.future.done():
                if error is not None:
                    item.future.set_exception(error)
                else:
                    item.future.cancel()
            self._release(item)
        if self.by_key.get(message.key) is message:
            del self.by_key[message.key]
            self.messages.remove(message)
        if not message.done.done():
            if error is not None:
                message.done.set_exception(error)
            else:
                message.done.set_result(None)

    async def _send(self, message: _Message, values: dict[str, object]) -> None:
        packet = ChatResponse(
            uuid=str(uuid5(NAMESPACE_URL, json.dumps(["agent-message", *message.key]))),
            text="", audio="", expression="", is_final_package=False,
            display_in_chat=message.delivery is d.OutputDelivery.CONVERSATION,
            is_ephemeral=message.delivery is d.OutputDelivery.EPHEMERAL_REACTION,
            packet_sequence=message.sequence,
        ).model_dump()
        packet.update(values)
        await self.connection.send_event("agent_message", packet)
        message.started = True
        message.sequence += 1
        message.ended = bool(packet["is_final_package"])

    async def _run(self) -> None:
        try:
            while self.messages and not self.closed:
                message = self.messages[0]
                if message.cancelled:
                    if message.started and not message.ended:
                        await self._send(message, {"is_final_package": True, "audio_error": True, "error_code": "TTS_CANCELLED"})
                    self._finish(message)
                    continue
                if not message.items:
                    self.changed.clear()
                    await self.changed.wait()
                    continue
                item = message.items.popleft()
                message.current = item
                try:
                    for values in payloads(item.output):
                        if message.cancelled or self.closed:
                            break
                        await self._send(message, values)
                    if not item.future.done():
                        if message.cancelled or self.closed:
                            item.future.cancel()
                        else:
                            item.future.set_result(None)
                except Exception as error:
                    if not item.future.done():
                        item.future.set_exception(error)
                    raise
                finally:
                    message.current = None
                    self._release(item)
                if message.ended:
                    self._finish(message)
        except Exception as error:
            get_logger(__name__).exception("WebSocket connection delivery stopped")
            self.closed = True
            self.connection.mark_disconnected()
            for message in list(self.messages):
                self._finish(message, error)
        except asyncio.CancelledError:
            self.disconnect()
            raise
