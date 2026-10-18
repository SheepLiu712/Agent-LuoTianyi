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
from src.domain.stage.connection import InteractionConnection
from src.domain.stage.transport import StageOutputSink
from src.infrastructure.media import MediaResolutionError, MediaResolutionErrorCode, PermanentMediaStore
from src.utils.logger import get_logger
from src.utils.owned_operation import complete_owned

from ..connection import AdapterConnection, AdapterConnectionError, OutboundDelivery
from ._delivery import _completion, _ConnectionDelivery, _DeliveryConfig
from ._input import _INPUT_EVENTS, _input_targets, _materialize_input, _process_input
from ._messages import _WSMessage
from ._peer import _ChatPeer
from ._protocol import _ack, _heartbeat, _parse, _reject, _update_model_types
from ._voice_upload_helper import _VoiceUploadAck, _VoiceUploadAssembler, _VoiceUploadError

if TYPE_CHECKING:
    from src.stage.chat_stage import ChatStage
    from src.stage.stage_manager import StageManager

logger = get_logger(__name__)


@dataclass
class _Binding:
    stage: ChatStage
    connection: _ChatPeer
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


class _ChatEventAcceptance(str, Enum):
    """Result of translating and submitting one authenticated chat event."""

    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    BAD_MESSAGE = "bad_message"
    UNSUPPORTED = "unsupported"
    OVERLOADED = "overloaded"


@dataclass(frozen=True)
class _EventRejection:
    """Stable negative acknowledgement details for a rejected event."""

    code: str
    message: str
    retryable: bool = False


_MEDIA_REJECTION_MESSAGES = {
    MediaResolutionErrorCode.TOO_LARGE.value: "图片过大（上限约 6 MB），请选择更小的图片",
    MediaResolutionErrorCode.UNSUPPORTED_TYPE.value: "不支持的图片格式",
    MediaResolutionErrorCode.NOT_CONFIGURED.value: "服务端未配置媒体存储",
}


class _ChatOutputSink:
    def __init__(self, adapter):
        self._adapter = adapter

    def submit_output(self, output: StageOutput) -> asyncio.Future[None]:
        return asyncio.shield(self._adapter._submit_output(output))


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
        self._input_lock = asyncio.Lock()
        self._voice_uploads = _VoiceUploadAssembler(
            self._media_store,
            max_incomplete=voice_config.get("max_incomplete", 128),
            ttl_seconds=voice_config.get("ttl_seconds", 600.0),
        )
        self._routes: dict[str, _Binding] = {}
        self._connections: dict[_ChatPeer, _ConnectionDelivery] = {}
        self._binding_lock = asyncio.Lock()
        self._recent_client_messages: OrderedDict[str, float] = OrderedDict()
        self._recent_client_msg_ttl_seconds = 600.0
        self._recent_client_msg_limit = 4096
        self._stage_manager: StageManager | None = None
        self._admission_lock = asyncio.Lock()
        self._peers: dict[AdapterConnection, _ChatPeer] = {}
        self._output_sink = _ChatOutputSink(self)
        self._client_executor = None
        self._closed = False
        self._max_inbound_bytes = (config or {}).get("max_inbound_frame_bytes", 128 * 1024)
        self._max_image_bytes = (config or {}).get("max_image_frame_bytes", 8 * 1024 * 1024 + 128 * 1024)

    def initialize(self, stage_manager: StageManager, *, client_executor=None) -> None:
        if self._stage_manager is not None and self._stage_manager is not stage_manager:
            raise RuntimeError("adapter already initialized")
        self._stage_manager = stage_manager
        self._client_executor = client_executor
        if client_executor is not None:
            client_executor.bind(self._live_peer)

    @property
    def output_sink(self) -> StageOutputSink:
        return self._output_sink

    def _live_peer(self, user_id):
        return next(
            (
                b.connection
                for b in self._routes.values()
                if b.connection.user_uuid == user_id and not b.connection.is_closed
            ),
            None,
        )

    async def open(
        self,
        *,
        user_id: str,
        connection_id: object,
        character_id: str | None = None,
        initial_message: str | bytes | None = None,
        capabilities: frozenset[str] = frozenset(),
    ) -> AdapterConnection:
        from src.stage.stage_manager import InteractionFinalizing, InteractionOwnedByCallAdmission

        if self._closed:
            raise ConnectionError("adapter is closed")
        handle = AdapterConnection()
        peer = _ChatPeer(user_id, connection_id, capabilities, self._config)
        self._peers[handle] = peer
        try:
            stage = await complete_owned(self._open(peer, character_id or self._default_character_id))
            peer.enqueue_event(
                "chat.ready",
                {"character_id": stage.character_id, "interaction_id": stage.interaction_id, "schema_version": 1},
            )
            peer._release_business_outputs()
            if initial_message is not None:
                await self.receive(handle, initial_message)
            return handle
        except BaseException as error:
            await self.disconnect(handle)
            if isinstance(error, (InteractionFinalizing, InteractionOwnedByCallAdmission)):
                raise AdapterConnectionError(
                    str(error),
                    close_code=1013,
                    initial_message=json.dumps(
                        {
                            "type": "error",
                            "ts": int(time.time() * 1000),
                            "payload": {
                                "code": str(error),
                                "message": "interaction is temporarily unavailable",
                                "retryable": True,
                            },
                        }
                    ),
                ) from error
            raise

    async def next_output(self, connection: AdapterConnection) -> OutboundDelivery:
        return await self._peer(connection).outbox.next()

    def complete_output(
        self, connection: AdapterConnection, delivery_id: str, *, error: Exception | None = None
    ) -> None:
        peer = self._peers.get(connection)
        if peer is not None:
            peer.outbox.complete(delivery_id, error)
            if error is not None:
                peer.mark_disconnected()

    def _peer(self, connection: AdapterConnection) -> _ChatPeer:
        peer = self._peers.get(connection)
        if peer is None or peer.is_closed:
            raise ConnectionError("connection is closed")
        return peer

    async def receive(self, connection: AdapterConnection, message: str | bytes) -> None:
        peer = self._peer(connection)
        event = _parse(peer, message, max_bytes=self._max_inbound_bytes, max_image_bytes=self._max_image_bytes)
        if event is None:
            return
        if event.event_type == "hb_ping":
            _heartbeat(peer, event)
            return
        if event.event_type == "llm_response":
            if self._client_executor is not None:
                self._client_executor.on_llm_response(event.payload, connection=peer)
            return
        if event.event_type in {"user_text", "user_image"}:
            _update_model_types(peer, event.payload)
        result = await self._receive(peer, event)
        self._respond(peer, event, result)

    @staticmethod
    def _respond(peer, event, result):
        if result is _ChatEventAcceptance.UNSUPPORTED:
            return
        if isinstance(result, _VoiceUploadAck):
            _ack(peer, event, payload=result.payload, duplicate=result.duplicate)
        elif isinstance(result, dict):
            peer.outbox.enqueue(json.dumps(result, ensure_ascii=False))
        elif isinstance(result, _EventRejection):
            _reject(peer, event, result.code, result.message, result.retryable)
        elif result in {_ChatEventAcceptance.ACCEPTED, _ChatEventAcceptance.DUPLICATE}:
            _ack(peer, event, duplicate=result is _ChatEventAcceptance.DUPLICATE)
        elif result is _ChatEventAcceptance.BAD_MESSAGE:
            _reject(peer, event, "BAD_MESSAGE", "chat event payload is invalid", False)
        else:
            _reject(peer, event, "OVERLOADED", "chat ingress queue is full", True)

    async def disconnect(self, connection: AdapterConnection) -> None:
        peer = self._peers.pop(connection, None)
        if peer is not None:
            if self._client_executor is not None:
                self._client_executor.clear_user(peer.user_uuid, peer)
            await complete_owned(self._close_connection(peer))

    async def close(self) -> None:
        await complete_owned(self._close())

    async def _close(self) -> None:
        self._closed = True
        for connection in tuple(self._peers):
            await self.disconnect(connection)

    async def _open(self, connection: _ChatPeer, character_id: str) -> ChatStage:
        if self._stage_manager is None:
            raise RuntimeError("adapter is not initialized")
        async with self._admission_lock:
            stage = await self._stage_manager.try_to_get_stage(
                user_id=connection.user_uuid,
                character_id=character_id,
                connection=connection,
            )
            try:
                await complete_owned(self._bind(stage, connection))
            except BaseException:
                await self._stage_manager.disconnect(connection)
                raise
            return stage

    async def _close_connection(self, connection: _ChatPeer) -> None:
        connection.mark_disconnected()
        for binding in tuple(self._routes.values()):
            if binding.connection is connection:
                await self.detach_stage_binding(binding.stage, connection)
        if self._stage_manager is not None:
            await self._stage_manager.disconnect(connection)

    async def _receive(
        self, connection: _ChatPeer, event: _WSMessage
    ) -> _ChatEventAcceptance | _EventRejection | _VoiceUploadAck | dict[str, str]:
        """统一接收普通刺激、语音上传阶段与切换命令；返回协议应答所需结果。"""
        if event.event_type == "call.switch_prepare":
            return await self._prepare_call_switch(connection, event)
        async with self._input_lock:
            return await self._try_accept_event(connection, event)

    async def _prepare_call_switch(self, connection: _ChatPeer, event: _WSMessage) -> _EventRejection | dict[str, str]:
        from src.adapter.websocket.call_v1.chat_switch import (
            CallSwitchProtocolError,
            make_switch_ready,
            parse_switch_prepare,
        )

        try:
            character_id, client_request_id = parse_switch_prepare(event.raw_text)
            if self._stage_manager is None:
                raise ValueError("adapter is not initialized")
            await self._stage_manager.prepare_call_transition(
                connection,
                character_id=character_id,
                client_request_id=client_request_id,
            )
            return make_switch_ready(character_id=character_id, client_request_id=client_request_id)
        except (CallSwitchProtocolError, ValueError) as error:
            code = error.code if isinstance(error, CallSwitchProtocolError) else "CALL_SWITCH_REJECTED"
            return _EventRejection(code, "call transition is not available")

    def _input_suspended(self, connection: _ChatPeer) -> bool:
        return any(b.stage.input_suspended for b in self._routes.values() if b.connection is connection)

    @staticmethod
    def _supports_input(event: _WSMessage) -> bool:
        """返回该协议适配器是否认识此业务输入类型。"""
        return event.event_type in _INPUT_EVENTS

    async def _try_accept_event(
        self,
        connection: _ChatPeer,
        event: _WSMessage,
    ) -> _ChatEventAcceptance | _EventRejection | _VoiceUploadAck:
        """Validate, deduplicate, translate, and submit one authenticated channel event."""
        if not self._supports_input(event):
            return _ChatEventAcceptance.UNSUPPORTED
        if connection.is_closed or not connection.user_uuid or not self._has_valid_client_message_id(event):
            return _ChatEventAcceptance.BAD_MESSAGE
        if self._input_suspended(connection):
            return _EventRejection(
                code="CALL_SWITCH_PENDING",
                message="chat input is suspended while call switching is pending",
                retryable=True,
            )
        try:
            if event.event_type != "user_voice" and self._is_duplicate_client_message(connection, event):
                return _ChatEventAcceptance.DUPLICATE
            accepted = await self._receive_event(connection, event)
        except _VoiceUploadError as error:
            return _EventRejection(error.code, error.message, error.retryable)
        except MediaResolutionError as error:
            code = error.code.value if isinstance(error.code, MediaResolutionErrorCode) else str(error.code)
            return _EventRejection(
                code=code,
                message=_MEDIA_REJECTION_MESSAGES.get(code, "图片无法读取或已损坏"),
            )
        except (KeyError, TypeError, ValueError):
            return _ChatEventAcceptance.BAD_MESSAGE
        if isinstance(accepted, _VoiceUploadAck):
            return accepted
        if not accepted:
            return _ChatEventAcceptance.OVERLOADED
        self._mark_client_message_accepted(connection, event)
        return _ChatEventAcceptance.ACCEPTED

    def _is_duplicate_client_message(self, connection: _ChatPeer, event: _WSMessage) -> bool:
        """Check accepted messages without marking a new event as accepted."""
        key = self._client_message_key(connection, event)
        if key is None:
            return False
        now = time.monotonic()
        self._prune_recent_client_messages(now)
        return key in self._recent_client_messages

    def _mark_client_message_accepted(self, connection: _ChatPeer, event: _WSMessage) -> bool:
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
    def _has_valid_client_message_id(event: _WSMessage) -> bool:
        return isinstance(event.client_msg_id, str) and 0 < len(event.client_msg_id) <= 128

    def _client_message_key(self, connection: _ChatPeer, event: _WSMessage) -> str | None:
        if not self._has_valid_client_message_id(event):
            return None
        owner = connection.user_uuid or "anonymous"
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

    def _submit_output(self, output: StageOutput) -> asyncio.Future[None]:
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

    async def _receive_event(self, connection: _ChatPeer, event: _WSMessage) -> bool | _VoiceUploadAck:
        """Process all business inputs, admit complete stimuli, then commit receipts."""
        try:
            return await self._process_and_deliver(connection, event)
        finally:
            self._voice_uploads.discard_prepared()
            # Failure/expiry belongs to the original upload binding, never a replacement.
            for binding, stimulus in self._voice_uploads.take_notifications():
                sink = _BoundInputSink(binding)
                if sink.can_accept(stimulus):
                    sink.submit(stimulus)

    async def _process_and_deliver(self, connection: _ChatPeer, event: _WSMessage) -> bool | _VoiceUploadAck:
        if connection.is_closed or not connection.user_uuid:
            raise ValueError("authenticated live connection required")
        bindings = {
            binding.stage.character_id: binding
            for binding in self._routes.values()
            if binding.connection is connection and binding.accepting
        }
        targets = _input_targets(event, self._default_character_id)
        if any(target not in bindings for target in targets):
            raise ValueError("target character is not bound to connection")
        # Capture binding identity before media awaits: rebinds must not retarget this input.
        sinks = [_BoundInputSink(bindings[target]) for target in targets]
        stimulus, status = await _process_input(
            event,
            connection.user_uuid,
            self._default_character_id,
            self._media_store,
            self._voice_uploads,
        )
        if status["state"] == "error":
            raise status["error"]
        if status["state"] == "complete":
            if "binding" in status:
                sinks = [_BoundInputSink(status["binding"])]
            if not await self._admit_input(event, stimulus, sinks):
                return self._reject_input_admission(event)
            if event.event_type == "user_voice":
                await self._voice_uploads.commit(bindings[targets[0]])
        elif status["state"] not in {"partial", "duplicate"}:
            raise RuntimeError("unknown input processing state")
        if event.event_type == "user_voice":
            return _VoiceUploadAck(status.get("ack_payload", {}), status.get("duplicate", False))
        return True

    async def _admit_input(self, event: _WSMessage, stimulus: d.Stimulus, sinks: list[_BoundInputSink]) -> bool:
        if not all(sink.can_accept(stimulus) for sink in sinks):
            return False
        if isinstance(stimulus, d.ImageMessage):
            await asyncio.to_thread(_materialize_input, event, stimulus, self._media_store)
        if not all(sink.can_accept(stimulus) for sink in sinks):
            return False
        return all(sink.submit(stimulus) for sink in sinks)

    @staticmethod
    def _reject_input_admission(event: _WSMessage) -> bool:
        if event.event_type == "user_voice":
            raise _VoiceUploadError("OVERLOADED", "chat ingress queue is full", retryable=True)
        return False

    async def detach_stage_binding(self, stage: ChatStage, connection: InteractionConnection | None = None) -> None:
        """Revoke only the matching Stage attachment; leave its physical socket open."""
        await complete_owned(self._unbind(stage, connection))

    async def _bind(self, stage: ChatStage, connection: _ChatPeer) -> None:
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

    async def _unbind(self, stage: ChatStage, connection: _ChatPeer | None) -> None:
        async with self._binding_lock:
            binding = self._routes.get(stage.interaction_id)
            if (
                binding is not None
                and binding.stage is stage
                and (connection is None or binding.connection is connection)
            ):
                await self._disconnect(binding)

    def _control(self, binding: _Binding, operation: Callable[[], Awaitable[None]]) -> asyncio.Future[None]:
        result = _completion(f"control interaction={binding.stage.interaction_id}")

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
