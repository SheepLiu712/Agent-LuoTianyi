"""聊天连接绑定：集中管理连接状态、Stage 投递权限、发送队列与完成反馈。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING
from uuid import uuid4

import src.domain.agent as d
from src.domain.agent import SinkRejectedError, SinkRejectionCode
from src.domain.stage import AgentPresentationChanged, CancelDelivery, StageOutput

from ..connection import OutboundDelivery
from ._delivery import ConnectionDelivery, create_completion
from ._protocol_translate import encode_event

if TYPE_CHECKING:
    from src.stage.chat_stage import ChatStage


class Binding:
    """持有一条连接及其 Stage 绑定，封装输入权限、投递调度和发送完成状态。"""

    def __init__(self, user_id: str, connection_id: object, capabilities, config) -> None:
        self._config = config
        self.stage: ChatStage | None = None
        self.accepting = False
        self._bound = False
        self._controls: set[asyncio.Task[None]] = set()
        self._delivery = ConnectionDelivery(self, config)
        self.user_uuid = user_id
        self.connection_id = connection_id
        self.capabilities = frozenset(capabilities)
        self.client_mode: dict = {"types": []}
        self.last_ping_id: int | None = None
        self._outbox = _Outbox(max_outputs=config.max_outputs, max_bytes=config.max_bytes)
        self.is_closed = False
        self._business_ready = asyncio.Event()

    def mark_disconnected(self) -> None:
        """标记连接失效并关闭 Outbox，唤醒等待业务就绪的发送者。"""
        self.is_closed = True
        self._outbox._close()
        self._business_ready.set()

    def release_business_outputs(self) -> None:
        """在 chat.ready 已入队后放行业务输出，保持就绪消息的发送顺序。"""
        self._business_ready.set()

    async def send(self, message: str | bytes) -> None:
        """等待业务就绪，将已编码报文入队并等待网络完成；取消等待不撤回已入队报文。"""
        await self._business_ready.wait()
        await asyncio.shield(self._outbox._enqueue(message))

    def enqueue(self, message: str | bytes) -> asyncio.Future[None]:
        """排队已编码的即时协议响应，返回网络发送完成的等待对象。"""
        return self._outbox._enqueue(message)

    async def next_output(self) -> OutboundDelivery:
        """取出待发送报文；实际发送结果须通过 complete_output 反馈。"""
        return await self._outbox._next()

    def complete_output(self, delivery_id: str, error: Exception | None = None) -> None:
        """反馈网络发送结果；发送失败时使整条连接失效。"""
        self._outbox._complete(delivery_id, error)
        if error is not None:
            self.mark_disconnected()

    def attach(self, stage: ChatStage) -> None:
        """首次绑定唯一 Stage；解绑后的 Binding 不复用，避免旧异步输入重新获得权限。"""
        if self.is_closed or self.user_uuid != stage.user_id:
            raise ValueError("connection user does not own stage")
        if self.stage is not None:
            raise ValueError("binding already assigned to a stage")
        self.stage = stage
        self.accepting = self._bound = True

    def can_accept(self, stimulus: d.Stimulus) -> bool:
        """检查绑定仍有效且唯一 Stage 允许接纳刺激。"""
        return (
            self.accepting
            and not self.is_closed
            and self.stage is not None
            and self.stage.stimulus_input_sink.can_accept(stimulus)
        )

    def submit(self, stimulus: d.Stimulus) -> bool:
        """重新检查准入并向绑定的 Stage 提交刺激。"""
        return self.can_accept(stimulus) and self.stage.stimulus_input_sink.submit(stimulus)

    async def detach(self) -> None:
        """永久撤销业务投递权限并完成输出收尾，保留连接发送协议控制响应的能力。"""
        if not self._bound:
            return
        self.accepting = False
        # Stage 在断开通知中仍可经原路由提交输出取消命令。
        await self.stage.connection_changed(d.ConnectionState.DISCONNECTED)
        self._bound = False
        if self.is_closed:
            self._delivery.disconnect()
        futures = self._delivery.cancel(self.stage.interaction_id)
        if futures:
            await asyncio.gather(*futures, return_exceptions=True)
        if self._controls:
            await asyncio.gather(*tuple(self._controls), return_exceptions=True)
        if self._delivery.task is not None:
            await asyncio.shield(self._delivery.task)

    def submit_output(self, output: StageOutput) -> asyncio.Future[None]:
        """接收业务输出或控制信号，返回实际投递结果 Future；无绑定或容量不足立即抛 SinkRejectedError。"""
        if not self._bound or self.is_closed or output.interaction_id != self.stage.interaction_id:
            raise d.SinkRejectedError("interaction is offline", code=d.SinkRejectionCode.SINK_CLOSED)
        delivery = self._delivery
        if isinstance(output, CancelDelivery):
            # 在返回前标记取消，下一轮 realize 可立即入队，无需等待网络收尾。
            futures = delivery.cancel(output.interaction_id, output.execution_id)

            async def _cancel_done() -> None:
                if futures:
                    await asyncio.gather(*futures)

            return self._control(_cancel_done)
        if isinstance(output, AgentPresentationChanged):
            if len(self._controls) >= self._config.max_outputs:
                raise d.SinkRejectedError("control queue is full", code=d.SinkRejectionCode.BACKPRESSURE_TIMEOUT)
            return self._control(
                lambda: self.send(encode_event("agent_state_changed", {"state": output.state.value})),
            )
        if type(output) not in (d.TextFinalOutput, d.ExpressionOutput, d.AudioChunkOutput, d.MessageEndOutput):
            raise d.SinkRejectedError("unsupported output", code=d.SinkRejectionCode.UNSUPPORTED_OUTPUT)
        return delivery.submit(output)

    def _control(self, operation: Callable[[], Awaitable[None]]) -> asyncio.Future[None]:
        result = create_completion(f"control interaction={self.stage.interaction_id}")

        async def _run() -> None:
            try:
                await operation()
            except asyncio.CancelledError:
                result.cancel()
                raise
            except Exception as error:
                if not result.done():
                    result.set_exception(error)
            else:
                if not result.done():
                    result.set_result(None)

        task = asyncio.create_task(_run(), name="websocket-control")
        self._controls.add(task)
        task.add_done_callback(self._controls.discard)
        return result


class _Outbox:
    """保存已编码报文及其发送完成等待对象，统一限制排队与在途容量。"""

    def __init__(self, *, max_outputs: int = 256, max_bytes: int = 16 * 1024 * 1024) -> None:
        self._queue: asyncio.Queue[OutboundDelivery | None] = asyncio.Queue()
        self._pending: dict[str, tuple[asyncio.Future[None], int]] = {}
        self._inflight: set[str] = set()
        self._bytes = 0
        self._max_outputs, self._max_bytes = max_outputs, max_bytes
        self._closed = False

    def _enqueue(self, message: str | bytes) -> asyncio.Future[None]:
        """接纳已编码报文并返回发送完成 Future；关闭或容量不足时拒绝入队。"""
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
        """接收指定投递的网络结果并完成等待对象；发送失败时关闭整个队列。"""
        if delivery_id not in self._inflight:
            return
        self._inflight.remove(delivery_id)
        self._settle(delivery_id, error)
        if error is not None:
            self._close(error)

    def _settle(self, delivery_id: str, error: Exception | None) -> None:
        future, size = self._pending.pop(delivery_id)
        self._bytes -= size
        if error is None:
            future.set_result(None)
        else:
            future.set_exception(error)

    def _close(self, error: Exception | None = None) -> None:
        """关闭队列，使未完成投递失败，并唤醒等待取报文的发送循环。"""
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
