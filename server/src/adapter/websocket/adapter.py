"""所有聊天共享的协议转换、连接绑定和异步投递入口。"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

import src.domain.agent as d
from src.domain.stage import AgentPresentationChanged, CancelDelivery, StageOutput
from src.infrastructure.media import MediaResolutionError, PermanentMediaStore
from src.utils.owned_operation import complete_owned
from src.web.websocket import WSMessage

from ._delivery import _ConnectionDelivery, _DeliveryConfig, completion
from ._input import _INPUT_EVENTS, materialize_image, prepare_input

if TYPE_CHECKING:
    from src.stage.chat_stage import ChatStage
    from src.web.websocket import WebSocketConnection


@dataclass
class _Binding:
    stage: ChatStage
    connection: WebSocketConnection
    controls: set[asyncio.Task[None]] = field(default_factory=set)


class ChatEventAcceptance(str, Enum):
    """Result of translating and submitting one authenticated chat event."""

    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    BAD_MESSAGE = "bad_message"
    UNSUPPORTED = "unsupported"
    OVERLOADED = "overloaded"


class WebSocketAdapter:
    """共享协议桥接层；每个交互绑定一个连接，同一连接按完整消息顺序发送。"""

    def __init__(self, config: dict | None = None, *, default_character_id: str = "luotianyi") -> None:
        """校验 config 中的投递容量限制，使用 default_character_id 补全未指定角色的输入。"""
        self._config = _DeliveryConfig.from_dict({} if config is None else config)
        media_config = (config or {}).get("media_store", {})
        self._media_store = (
            PermanentMediaStore(media_config) if isinstance(media_config, dict) and media_config.get("root") else None
        )
        self._default_character_id = default_character_id
        self._routes: dict[str, _Binding] = {}
        self._connections: dict[WebSocketConnection, _ConnectionDelivery] = {}
        self._binding_lock = asyncio.Lock()
        self._recent_client_messages: OrderedDict[str, float] = OrderedDict()
        self._recent_client_msg_ttl_seconds = 600.0
        self._recent_client_msg_limit = 4096

    @staticmethod
    def supports_input(event: WSMessage) -> bool:
        """返回该协议适配器是否认识此业务输入类型。"""
        return event.event_type in _INPUT_EVENTS

    async def try_accept_event(
        self,
        connection: WebSocketConnection,
        event: WSMessage,
    ) -> ChatEventAcceptance:
        """Validate, deduplicate, translate, and submit one authenticated channel event."""
        if not self.supports_input(event):
            return ChatEventAcceptance.UNSUPPORTED
        if connection.is_closed or not connection.user_uuid or not self.has_valid_client_message_id(event):
            return ChatEventAcceptance.BAD_MESSAGE
        try:
            if self.is_duplicate_client_message(connection, event):
                return ChatEventAcceptance.DUPLICATE
            accepted = await self.receive_event(connection, event)
        except (KeyError, MediaResolutionError, TypeError, ValueError):
            return ChatEventAcceptance.BAD_MESSAGE
        if not accepted:
            return ChatEventAcceptance.OVERLOADED
        self.mark_client_message_accepted(connection, event)
        return ChatEventAcceptance.ACCEPTED

    def is_duplicate_client_message(self, connection: WebSocketConnection, event: WSMessage) -> bool:
        """Check accepted messages without marking a new event as accepted."""
        key = self._client_message_key(connection, event)
        if key is None:
            return False
        now = time.monotonic()
        self._prune_recent_client_messages(now)
        return key in self._recent_client_messages

    def mark_client_message_accepted(self, connection: WebSocketConnection, event: WSMessage) -> bool:
        """Record idempotency only after every target Stage accepted the event."""
        key = self._client_message_key(connection, event)
        if key is None:
            return False
        now = time.monotonic()
        self._prune_recent_client_messages(now)
        self._recent_client_messages[key] = now
        self._recent_client_messages.move_to_end(key)
        while len(self._recent_client_messages) > self._recent_client_msg_limit:
            self._recent_client_messages.popitem(last=False)
        return True

    @staticmethod
    def has_valid_client_message_id(event: WSMessage) -> bool:
        return isinstance(event.client_msg_id, str) and 0 < len(event.client_msg_id) <= 128

    def _client_message_key(self, connection: WebSocketConnection, event: WSMessage) -> str | None:
        if not self.has_valid_client_message_id(event):
            return None
        owner = connection.user_uuid or connection.user_name or "anonymous"
        return f"{owner}:{event.client_msg_id}"

    def _prune_recent_client_messages(self, now: float) -> None:
        expired_before = now - self._recent_client_msg_ttl_seconds
        while self._recent_client_messages:
            _, accepted_at = next(iter(self._recent_client_messages.items()))
            if accepted_at >= expired_before:
                break
            self._recent_client_messages.popitem(last=False)

    def submit_output(self, output: StageOutput) -> asyncio.Future[None]:
        """接收业务输出或控制信号，返回实际投递结果 Future；无绑定或容量不足立即抛 SinkRejectedError。"""
        binding = self._routes.get(output.interaction_id)
        if binding is None or binding.connection.is_closed:
            raise d.SinkRejectedError("interaction is offline", code=d.SinkRejectionCode.SINK_CLOSED)
        delivery = self._connections[binding.connection]
        if isinstance(output, CancelDelivery):
            # 在返回前标记取消，下一轮 realize 可立即入队，无需等待网络收尾。
            futures = delivery.cancel(output.interaction_id, output.execution_id)

            async def cancel_done() -> None:
                if futures:
                    await asyncio.gather(*futures)

            return self._control(binding, cancel_done)
        if isinstance(output, AgentPresentationChanged):
            if (
                sum(len(route.controls) for route in self._routes.values() if route.connection is binding.connection)
                >= self._config.max_outputs
            ):
                raise d.SinkRejectedError("control queue is full", code=d.SinkRejectionCode.BACKPRESSURE_TIMEOUT)
            return self._control(
                binding, lambda: binding.connection.send_event("agent_state_changed", {"state": output.state.value})
            )
        if type(output) not in (d.TextFinalOutput, d.ExpressionOutput, d.AudioChunkOutput, d.MessageEndOutput):
            raise d.SinkRejectedError("unsupported output", code=d.SinkRejectionCode.UNSUPPORTED_OUTPUT)
        return delivery.submit(output)

    async def receive_event(self, connection: WebSocketConnection, event: WSMessage) -> bool:
        """将已认证业务 event 转为刺激并交给已绑定 Stage；全部目标可接收才投递，否则返回 False。"""
        if connection.is_closed or not connection.user_uuid:
            raise ValueError("authenticated live connection required")
        candidate = prepare_input(
            event,
            connection.user_uuid,
            self._default_character_id,
            self._media_store,
        )
        stimulus = candidate.stimulus
        stages = {
            binding.stage.character_id: binding.stage
            for binding in self._routes.values()
            if binding.connection is connection
        }
        if any(target not in stages for target in stimulus.target_character_ids):
            raise ValueError("target character is not bound to connection")
        sinks = [stages[target].stimulus_input_sink for target in stimulus.target_character_ids]
        # 同一事件循环内检查与入队之间无 await，避免多角色部分接收。
        if not all(sink.can_accept(stimulus) for sink in sinks):
            return False
        if candidate.image_base64 is not None:
            if self._media_store is None:
                raise ValueError("media store is not configured")
            await asyncio.to_thread(materialize_image, candidate, self._media_store)
        for sink in sinks:
            sink.submit(stimulus)
        return True

    async def bind(self, stage: ChatStage, connection: WebSocketConnection) -> None:
        """将 stage 绑定到同用户 connection；重绑先停止旧执行，完成旧连接收尾后通知 Stage 上线。"""
        await complete_owned(self._bind(stage, connection))

    async def disconnect(self, stage: ChatStage, connection: WebSocketConnection | None = None) -> None:
        """拆开 stage 的绑定并完成任务清理；给出 connection 时仅拆除该连接，避免旧断线通知影响重连。"""
        await complete_owned(self._unbind(stage, connection))

    async def _bind(self, stage: ChatStage, connection: WebSocketConnection) -> None:
        async with self._binding_lock:
            if connection.is_closed or not connection.user_uuid or connection.user_uuid != stage.user_id:
                raise ValueError("connection user does not own stage")
            old = self._routes.get(stage.interaction_id)
            if old is not None:
                if old.stage is not stage:
                    raise ValueError("interaction already owned by another stage")
                if old.connection is connection:
                    await stage.connection_changed(d.ConnectionState.CONNECTED)
                    return
                await self._disconnect(old)
            if connection.is_closed:
                raise ValueError("connection closed during binding")
            if any(
                route.connection is connection and route.stage.character_id == stage.character_id
                for route in self._routes.values()
            ):
                raise ValueError("character already bound to connection")
            self._routes[stage.interaction_id] = _Binding(stage, connection)
            self._connections.setdefault(connection, _ConnectionDelivery(connection, self._config))
            try:
                await stage.connection_changed(d.ConnectionState.CONNECTED)
            except BaseException:
                await self._disconnect(self._routes[stage.interaction_id])
                raise

    async def _unbind(self, stage: ChatStage, connection: WebSocketConnection | None) -> None:
        async with self._binding_lock:
            binding = self._routes.get(stage.interaction_id)
            if (
                binding is not None
                and binding.stage is stage
                and (connection is None or binding.connection is connection)
            ):
                await self._disconnect(binding)

    def _control(self, binding: _Binding, operation: Callable[[], Awaitable[None]]) -> asyncio.Future[None]:
        result = completion(f"control interaction={binding.stage.interaction_id}")

        async def run() -> None:
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

        task = asyncio.create_task(run(), name="websocket-control")
        binding.controls.add(task)
        task.add_done_callback(binding.controls.discard)
        return result

    async def _disconnect(self, binding: _Binding) -> None:
        stage, connection = binding.stage, binding.connection
        delivery = self._connections[connection]
        # 先阻止 Stage 继续产出，Stage 可在此过程中通过原绑定提交取消命令。
        await stage.connection_changed(d.ConnectionState.DISCONNECTED)
        self._routes.pop(stage.interaction_id, None)
        if connection.is_closed:
            delivery.disconnect()
        futures = delivery.cancel(stage.interaction_id)
        if futures:
            await asyncio.gather(*futures, return_exceptions=True)
        if binding.controls:
            await asyncio.gather(*tuple(binding.controls), return_exceptions=True)
        if not any(route.connection is connection for route in self._routes.values()):
            if delivery.task is not None:
                await asyncio.shield(delivery.task)
            self._connections.pop(connection, None)
