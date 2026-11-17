"""按逻辑连接串行调度完整业务消息，保持消息顺序和取消终包位置。"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, uuid5

import src.domain.agent as d
from src.utils.logger import get_logger

from ._messages import ChatResponse
from ._protocol_translate import encode_event, payloads

if TYPE_CHECKING:
    from ._binding import Binding


@dataclass(frozen=True)
class DeliveryConfig:
    """定义单连接业务输出数量、字节数和逻辑消息数的容量上限。"""

    max_outputs: int = 256
    max_bytes: int = 16 * 1024 * 1024
    max_messages: int = 64

    @classmethod
    def from_dict(cls, config: dict) -> DeliveryConfig:
        """读取并校验投递容量配置；各上限必须为正整数。"""
        if not isinstance(config, dict):
            raise TypeError("adapter config must be a dictionary")
        values = {
            key: config.get(key, default)
            for key, default in (("max_outputs", 256), ("max_bytes", 16 * 1024 * 1024), ("max_messages", 64))
        }
        if any(type(value) is not int or value <= 0 for value in values.values()):
            raise ValueError("adapter queue limits must be positive integers")
        return cls(**values)


def create_completion(label: str) -> asyncio.Future[None]:
    """创建投递完成 Future，并记录未成功完成的投递异常。"""
    future = asyncio.get_running_loop().create_future()

    def _observe(result: asyncio.Future[None]) -> None:
        if not result.cancelled() and result.exception() is not None:
            get_logger(__name__).error("WebSocket delivery failed %s: %s", label, result.exception())

    future.add_done_callback(_observe)
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
    message_id: str | None = None
    items: deque[_Item] = field(default_factory=deque)
    accepted_end: bool = False
    cancelled: bool = False
    started: bool = False
    ended: bool = False
    sequence: int = 0
    current: _Item | None = None


class ConnectionDelivery:
    """按逻辑消息串行调度业务输出，管理容量、取消、包序号和终包。"""

    def __init__(self, connection: Binding, config: DeliveryConfig) -> None:
        self.connection, self.config = connection, config
        self.messages: deque[_Message] = deque()
        self.by_key: dict[tuple[str, str, str], _Message] = {}
        self.pending_outputs = 0
        self.pending_bytes = 0
        self.changed = asyncio.Event()
        self.task: asyncio.Task[None] | None = None
        self.closed = False

    def submit(self, output: d.AgentOutput) -> asyncio.Future[None]:
        """接纳一个业务输出并返回其网络完成 Future；身份冲突、关闭或容量不足时拒绝。"""
        if self.closed or self.connection.is_closed:
            raise d.SinkRejectedError("connection is closed", code=d.SinkRejectionCode.SINK_CLOSED)
        key = (output.interaction_id, output.execution_id, output.action_id)
        message = self.by_key.get(key)
        if message is not None and (message.accepted_end or message.cancelled or message.delivery != output.delivery):
            raise d.SinkRejectedError(
                "message already ended or delivery changed", code=d.SinkRejectionCode.CONTENT_CONFLICT
            )
        if message is not None and message.message_id != output.message_id:
            raise d.SinkRejectedError("message identity changed", code=d.SinkRejectionCode.CONTENT_CONFLICT)
        size = len(output.data) if isinstance(output, d.AudioChunkOutput) else len(str(output).encode("utf-8"))
        if (
            self.pending_outputs >= self.config.max_outputs
            or self.pending_bytes + size > self.config.max_bytes
            or (message is None and len(self.messages) >= self.config.max_messages)
        ):
            raise d.SinkRejectedError("connection output queue is full", code=d.SinkRejectionCode.BACKPRESSURE_TIMEOUT)
        if message is None:
            message = _Message(key, output.delivery, create_completion(f"message={key}"), output.message_id)
            self.messages.append(message)
            self.by_key[key] = message
        future = create_completion(f"interaction={key[0]} execution={key[1]} sequence={output.sequence_no}")
        message.items.append(_Item(output, future, size))
        message.accepted_end = isinstance(output, d.MessageEndOutput)
        self.pending_outputs += 1
        self.pending_bytes += size
        self.changed.set()
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._run(), name="websocket-output")
        return future

    def cancel(self, interaction_id: str, execution_id: str | None = None) -> list[asyncio.Future[None]]:
        """取消匹配交互或执行的未发送输出，返回各消息完成取消收尾的等待对象。"""
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
        """终止该连接的业务投递，使所有未完成消息失败。"""
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
            uuid=message.message_id or str(uuid5(NAMESPACE_URL, json.dumps(["agent-message", *message.key]))),
            text="",
            audio="",
            expression="",
            is_final_package=False,
            display_in_chat=message.delivery is d.OutputDelivery.CONVERSATION,
            is_ephemeral=message.delivery is d.OutputDelivery.EPHEMERAL_REACTION,
            packet_sequence=message.sequence,
        ).model_dump()
        packet.update(values)
        await self.connection.send(encode_event("agent_message", packet))
        message.started = True
        message.sequence += 1
        message.ended = bool(packet["is_final_package"])

    async def _run(self) -> None:
        try:
            while self.messages and not self.closed:
                await self._deliver_next_message()
        except Exception as error:
            self._fail(error)
        except asyncio.CancelledError:
            self.disconnect()
            raise

    async def _deliver_next_message(self) -> None:
        message = self.messages[0]
        if message.cancelled:
            await self._finish_cancelled(message)
            return
        if not message.items:
            self.changed.clear()
            await self.changed.wait()
            return
        await self._deliver_item(message, message.items.popleft())
        if message.ended:
            self._finish(message)

    async def _finish_cancelled(self, message: _Message) -> None:
        if message.started and not message.ended:
            await self._send(
                message,
                {"is_final_package": True, "audio_error": True, "error_code": "TTS_CANCELLED"},
            )
        self._finish(message)

    async def _deliver_item(self, message: _Message, item: _Item) -> None:
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

    def _fail(self, error: Exception) -> None:
        get_logger(__name__).exception("WebSocket connection delivery stopped")
        self.closed = True
        self.connection.mark_disconnected()
        for message in list(self.messages):
            self._finish(message, error)
