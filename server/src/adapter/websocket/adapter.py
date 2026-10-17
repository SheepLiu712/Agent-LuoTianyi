"""所有聊天共享的协议转换、连接绑定和异步投递入口。"""

from __future__ import annotations

import asyncio
import json
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

import src.domain.agent as d
from src.domain.stage import AgentPresentationChanged, CancelDelivery, StageOutput
from src.infrastructure.media import MediaResolutionError, MediaResolutionErrorCode, PermanentMediaStore
from src.utils.logger import get_logger
from src.utils.owned_operation import complete_owned
from src.web.websocket import WSMessage

from ._delivery import _ConnectionDelivery, _DeliveryConfig, completion
from ._input import _INPUT_EVENTS, materialize_image, prepare_input
from .voice_upload import VoiceUploadAck, VoiceUploadAssembler, VoiceUploadError

if TYPE_CHECKING:
    from src.stage.chat_stage import ChatStage
    from src.stage.stage_manager import StageManager
    from src.web.websocket import WebSocketConnection

logger = get_logger(__name__)


@dataclass
class _Binding:
    stage: ChatStage
    connection: WebSocketConnection
    controls: set[asyncio.Task[None]] = field(default_factory=set)
    accepting: bool = True


class _BoundInputSink:
    """异步上传只能向发起该次投递的有效绑定提交刺激。"""

    def __init__(self, binding: _Binding) -> None:
        self._binding = binding

    def can_accept(self, stimulus: d.Stimulus) -> bool:
        binding = self._binding
        return (
            binding.accepting
            and not binding.connection.is_closed
            and binding.stage.stimulus_input_sink.can_accept(stimulus)
        )

    def submit(self, stimulus: d.Stimulus) -> bool:
        return self.can_accept(stimulus) and self._binding.stage.stimulus_input_sink.submit(stimulus)


class ChatEventAcceptance(str, Enum):
    """Result of translating and submitting one authenticated chat event."""

    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    BAD_MESSAGE = "bad_message"
    UNSUPPORTED = "unsupported"
    OVERLOADED = "overloaded"


@dataclass(frozen=True)
class EventRejection:
    """Stable negative acknowledgement details for a rejected event."""

    code: str
    message: str
    retryable: bool = False


_MEDIA_REJECTION_MESSAGES = {
    MediaResolutionErrorCode.TOO_LARGE.value: "图片过大（上限约 6 MB），请选择更小的图片",
    MediaResolutionErrorCode.UNSUPPORTED_TYPE.value: "不支持的图片格式",
    MediaResolutionErrorCode.NOT_CONFIGURED.value: "服务端未配置媒体存储",
}


class WebSocketAdapter:
    """共享协议桥接层；每个交互绑定一个连接，同一连接按完整消息顺序发送。"""

    def __init__(self, config: dict | None = None, *, default_character_id: str = "luotianyi") -> None:
        """校验 config 中的投递容量限制，使用 default_character_id 补全未指定角色的输入。"""
        self._config = _DeliveryConfig.from_dict({} if config is None else config)
        media_config = (config or {}).get("media_store", {})
        self._media_store = (
            PermanentMediaStore(media_config) if isinstance(media_config, dict) and media_config.get("root") else None
        )
        if self._media_store is None:
            logger.warning("媒体存储未配置，图片发送将被拒绝")
        self._default_character_id = default_character_id
        voice_config = (config or {}).get("voice_upload", {})
        if not isinstance(voice_config, dict):
            raise TypeError("voice_upload config must be a dictionary")
        self._voice_uploads = VoiceUploadAssembler(
            self._media_store,
            max_incomplete=voice_config.get("max_incomplete", 128),
            ttl_seconds=voice_config.get("ttl_seconds", 600.0),
        )
        self._routes: dict[str, _Binding] = {}
        self._connections: dict[WebSocketConnection, _ConnectionDelivery] = {}
        self._binding_lock = asyncio.Lock()
        self._recent_client_messages: OrderedDict[str, float] = OrderedDict()
        self._recent_client_msg_ttl_seconds = 600.0
        self._recent_client_msg_limit = 4096
        self._stage_manager: StageManager | None = None
        self._admission_lock = asyncio.Lock()

    def initialize(self, stage_manager: StageManager) -> None:
        if self._stage_manager is not None and self._stage_manager is not stage_manager:
            raise RuntimeError("adapter already initialized")
        self._stage_manager = stage_manager

    async def open(self, connection: WebSocketConnection, character_id: str) -> ChatStage:
        return await complete_owned(self._open(connection, character_id))

    async def _open(self, connection: WebSocketConnection, character_id: str) -> ChatStage:
        if self._stage_manager is None:
            raise RuntimeError("adapter is not initialized")
        async with self._admission_lock:
            stage = await self._stage_manager.try_to_get_stage(
                user_id=connection.user_uuid,
                character_id=character_id,
                connection=connection,
            )
            try:
                await self.bind(stage, connection)
            except BaseException:
                await self._stage_manager.disconnect(connection)
                raise
            return stage

    async def close_connection(self, connection: WebSocketConnection) -> None:
        await complete_owned(self._close_connection(connection))

    async def _close_connection(self, connection: WebSocketConnection) -> None:
        connection.mark_disconnected()
        for binding in tuple(self._routes.values()):
            if binding.connection is connection:
                await self.disconnect(binding.stage, connection)
        if self._stage_manager is not None:
            await self._stage_manager.disconnect(connection)

    async def receive(
        self, connection: WebSocketConnection, event: WSMessage
    ) -> ChatEventAcceptance | EventRejection | VoiceUploadAck | dict[str, str]:
        """统一接收普通刺激、语音上传阶段与切换命令；返回协议应答所需结果。"""
        if event.event_type == "call.switch_prepare":
            return await self._prepare_call_switch(connection, event)
        if event.event_type == "user_voice":
            try:
                return await self._process_voice_event(connection, event)
            except VoiceUploadError as error:
                return EventRejection(error.code, error.message, error.retryable)
            except (TypeError, ValueError):
                return ChatEventAcceptance.BAD_MESSAGE
        return await self._try_accept_event(connection, event)

    async def _prepare_call_switch(
        self, connection: WebSocketConnection, event: WSMessage
    ) -> EventRejection | dict[str, str]:
        from .call_v1 import ControlProtocolError, decode_control_text

        try:
            message = decode_control_text(
                json.dumps(event.raw_event, ensure_ascii=False), sender="client", transport="chat_ws"
            )
            if self._stage_manager is None:
                raise ValueError("adapter is not initialized")
            await self._stage_manager.prepare_call_transition(
                connection,
                character_id=str(message["character_id"]),
                client_request_id=str(message["client_request_id"]),
            )
            return {
                "protocol": "call.v1",
                "type": "call.switch_ready",
                "client_request_id": str(message["client_request_id"]),
                "character_id": str(message["character_id"]),
            }
        except (ControlProtocolError, ValueError) as error:
            code = error.code if isinstance(error, ControlProtocolError) else "CALL_SWITCH_REJECTED"
            return EventRejection(code, "call transition is not available")

    def _input_suspended(self, connection: WebSocketConnection) -> bool:
        return any(b.stage.input_suspended for b in self._routes.values() if b.connection is connection)

    @staticmethod
    def supports_input(event: WSMessage) -> bool:
        """返回该协议适配器是否认识此业务输入类型。"""
        return event.event_type in _INPUT_EVENTS

    async def _try_accept_event(
        self,
        connection: WebSocketConnection,
        event: WSMessage,
    ) -> ChatEventAcceptance | EventRejection:
        """Validate, deduplicate, translate, and submit one authenticated channel event."""
        if not self.supports_input(event):
            return ChatEventAcceptance.UNSUPPORTED
        if connection.is_closed or not connection.user_uuid or not self._has_valid_client_message_id(event):
            return ChatEventAcceptance.BAD_MESSAGE
        if self._input_suspended(connection):
            return EventRejection(
                code="CALL_SWITCH_PENDING",
                message="chat input is suspended while call switching is pending",
                retryable=True,
            )
        try:
            if self._is_duplicate_client_message(connection, event):
                return ChatEventAcceptance.DUPLICATE
            accepted = await self._receive_event(connection, event)
        except MediaResolutionError as error:
            code = error.code.value if isinstance(error.code, MediaResolutionErrorCode) else str(error.code)
            return EventRejection(
                code=code,
                message=_MEDIA_REJECTION_MESSAGES.get(code, "图片无法读取或已损坏"),
            )
        except (KeyError, TypeError, ValueError):
            return ChatEventAcceptance.BAD_MESSAGE
        if not accepted:
            return ChatEventAcceptance.OVERLOADED
        self._mark_client_message_accepted(connection, event)
        return ChatEventAcceptance.ACCEPTED

    async def _process_voice_event(self, connection: WebSocketConnection, event: WSMessage) -> VoiceUploadAck:
        """把一个语音上传阶段交给 assembler；阶段幂等不经过普通消息去重表。"""
        if connection.is_closed or not connection.user_uuid:
            raise ValueError("authenticated live connection required")
        if self._input_suspended(connection):
            raise VoiceUploadError(
                code="CALL_SWITCH_PENDING",
                message="chat input is suspended while call switching is pending",
                retryable=True,
            )
        payload = event.payload if isinstance(event.payload, dict) else {}
        character_id = payload.get("target_character_id", payload.get("character_id", self._default_character_id))
        raw_targets = payload.get("target_character_ids")
        if raw_targets is not None:
            if not isinstance(raw_targets, list) or len(raw_targets) != 1:
                raise ValueError("voice upload requires exactly one target character")
            character_id = raw_targets[0]
        if not isinstance(character_id, str) or not character_id.strip():
            raise ValueError("invalid target character")
        stage = next(
            (
                binding.stage
                for binding in self._routes.values()
                if binding.connection is connection and binding.stage.character_id == character_id
            ),
            None,
        )
        if stage is None:
            raise ValueError("target character is not bound to connection")
        return await self._voice_uploads.process(
            event=event,
            user_id=connection.user_uuid,
            character_id=character_id,
            sink=_BoundInputSink(self._routes[stage.interaction_id]),
        )

    def _is_duplicate_client_message(self, connection: WebSocketConnection, event: WSMessage) -> bool:
        """Check accepted messages without marking a new event as accepted."""
        key = self._client_message_key(connection, event)
        if key is None:
            return False
        now = time.monotonic()
        self._prune_recent_client_messages(now)
        return key in self._recent_client_messages

    def _mark_client_message_accepted(self, connection: WebSocketConnection, event: WSMessage) -> bool:
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
    def _has_valid_client_message_id(event: WSMessage) -> bool:
        return isinstance(event.client_msg_id, str) and 0 < len(event.client_msg_id) <= 128

    def _client_message_key(self, connection: WebSocketConnection, event: WSMessage) -> str | None:
        if not self._has_valid_client_message_id(event):
            return None
        owner = connection.user_uuid or connection.user_name or "anonymous"
        if event.event_type in {"user_voice_recording_started", "user_voice_recording_cancelled"}:
            payload = event.payload if isinstance(event.payload, dict) else {}
            recording_id = payload.get("recording_id")
            if isinstance(recording_id, str) and recording_id.strip():
                return f"{owner}:{event.event_type}:{recording_id}"
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

    async def _receive_event(self, connection: WebSocketConnection, event: WSMessage) -> bool:
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
        bindings = {
            binding.stage.character_id: binding
            for binding in self._routes.values()
            if binding.connection is connection and binding.accepting
        }
        if any(target not in bindings for target in stimulus.target_character_ids):
            raise ValueError("target character is not bound to connection")
        sinks = [_BoundInputSink(bindings[target]) for target in stimulus.target_character_ids]
        # 先检查容量，避免为已拒绝的输入落盘；异步转换后还需复查。
        if not all(sink.can_accept(stimulus) for sink in sinks):
            return False
        if candidate.image_base64 is not None:
            if self._media_store is None:
                raise ValueError("media store is not configured")
            await asyncio.to_thread(materialize_image, candidate, self._media_store)
        if not all(sink.can_accept(stimulus) for sink in sinks):
            return False
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
        binding.accepting = False
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
