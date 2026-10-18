"""所有聊天共享的协议转换、连接绑定和异步投递入口。"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

import src.domain.agent as d
from src.domain.stage import StageOutput
from src.domain.stage.connection import InteractionConnection
from src.domain.stage.transport import StageOutputSink
from src.infrastructure.media import MediaResolutionError, MediaResolutionErrorCode, PermanentMediaStore
from src.utils.logger import get_logger
from src.utils.owned_operation import complete_owned

from ..connection import AdapterConnection, AdapterConnectionError, OutboundDelivery
from ._binding import Binding
from ._delivery import DeliveryConfig
from ._input import _INPUT_EVENTS, input_targets, materialize_input, process_input
from ._messages import WSMessage
from ._protocol_translate import (
    ack,
    encode_event,
    encode_message,
    enqueue_event,
    heartbeat,
    parse,
    reject,
    update_model_types,
)
from ._voice_upload_helper import VoiceUploadAck, VoiceUploadAssembler, VoiceUploadError

if TYPE_CHECKING:
    from src.stage.chat_stage import ChatStage
    from src.stage.stage_manager import StageManager

logger = get_logger(__name__)


class _ChatEventAcceptance(str, Enum):
    """已鉴权聊天事件的转换与提交结果。"""

    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    BAD_MESSAGE = "bad_message"
    UNSUPPORTED = "unsupported"
    OVERLOADED = "overloaded"


@dataclass(frozen=True)
class _EventRejection:
    """拒绝事件所需的稳定错误码、说明和可重试性。"""

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
        """将 Stage 输出交给 Adapter，返回对应投递完成的等待对象。"""
        return asyncio.shield(self._adapter._submit_output(output))


class WebSocketAdapter:
    """共享协议桥接层；每个连接只绑定一个 Stage，并按完整消息顺序发送。"""

    def __init__(self, config: dict | None = None, *, default_character_id: str = "luotianyi") -> None:
        """校验 config 中的投递容量限制，使用 default_character_id 补全未指定角色的输入。"""
        self._config = DeliveryConfig.from_dict({} if config is None else config)
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
        self._voice_uploads = VoiceUploadAssembler(
            self._media_store,
            max_incomplete=voice_config.get("max_incomplete", 128),
            ttl_seconds=voice_config.get("ttl_seconds", 600.0),
        )
        self._routes: dict[str, Binding] = {}
        self._binding_lock = asyncio.Lock()
        self._recent_client_messages: OrderedDict[str, float] = OrderedDict()
        self._recent_client_msg_ttl_seconds = 600.0
        self._recent_client_msg_limit = 4096
        self._stage_manager: StageManager | None = None
        self._admission_lock = asyncio.Lock()
        self._bindings: dict[AdapterConnection, Binding] = {}
        self._output_sink = _ChatOutputSink(self)
        self._client_executor = None
        self._closed = False
        self._max_inbound_bytes = (config or {}).get("max_inbound_frame_bytes", 128 * 1024)
        self._max_image_bytes = (config or {}).get("max_image_frame_bytes", 8 * 1024 * 1024 + 128 * 1024)

    def initialize(self, stage_manager: StageManager, *, client_executor=None) -> None:
        """绑定 StageManager 和可选客户端模型执行器；不允许替换已绑定的管理器。"""
        if self._stage_manager is not None and self._stage_manager is not stage_manager:
            raise RuntimeError("adapter already initialized")
        self._stage_manager = stage_manager
        self._client_executor = client_executor
        if client_executor is not None:
            client_executor.bind(self._live_binding)

    @property
    def output_sink(self) -> StageOutputSink:
        """提供面向 Stage 的业务输出端口，隐藏连接路由和投递调度。"""
        return self._output_sink

    def _live_binding(self, user_id):
        return next(
            (b for b in self._routes.values() if b.user_uuid == user_id and not b.is_closed),
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
        """为已鉴权连接获取并绑定聊天 Stage，先排队 chat.ready 再放行业务输出，返回连接句柄。"""
        from src.stage.stage_manager import InteractionFinalizing, InteractionOwnedByCallAdmission

        if self._closed:
            raise ConnectionError("adapter is closed")
        handle = AdapterConnection()
        binding = Binding(user_id, connection_id, capabilities, self._config)
        self._bindings[handle] = binding
        try:
            stage = await complete_owned(self._open(binding, character_id or self._default_character_id))
            enqueue_event(
                binding,
                "chat.ready",
                {"character_id": stage.character_id, "interaction_id": stage.interaction_id, "schema_version": 1},
            )
            binding.release_business_outputs()
            if initial_message is not None:
                await self.receive(handle, initial_message)
            return handle
        except BaseException as error:
            await self.disconnect(handle)
            if isinstance(error, (InteractionFinalizing, InteractionOwnedByCallAdmission)):
                raise AdapterConnectionError(
                    str(error),
                    close_code=1013,
                    initial_message=encode_event(
                        "error",
                        {
                            "code": str(error),
                            "message": "interaction is temporarily unavailable",
                            "retryable": True,
                        },
                    ),
                ) from error
            raise

    async def next_output(self, connection: AdapterConnection) -> OutboundDelivery:
        """取得连接的下一条已编码报文；网络发送结果须另行反馈。"""
        return await self._binding(connection).next_output()

    def complete_output(
        self, connection: AdapterConnection, delivery_id: str, *, error: Exception | None = None
    ) -> None:
        """反馈本次网络发送的成功或失败，完成对应等待对象；失败时标记连接失效。"""
        binding = self._bindings.get(connection)
        if binding is not None:
            binding.complete_output(delivery_id, error)

    def _binding(self, connection: AdapterConnection) -> Binding:
        binding = self._bindings.get(connection)
        if binding is None or binding.is_closed:
            raise ConnectionError("connection is closed")
        return binding

    async def receive(self, connection: AdapterConnection, message: str | bytes) -> None:
        """处理一条原始聊天报文，路由控制消息和业务输入，并按处理及投递结果排队应答。"""
        binding = self._binding(connection)
        event = parse(binding, message, max_bytes=self._max_inbound_bytes, max_image_bytes=self._max_image_bytes)
        if event is None:
            return
        if event.event_type == "hb_ping":
            heartbeat(binding, event)
            return
        if event.event_type == "llm_response":
            if self._client_executor is not None:
                self._client_executor.on_llm_response(event.payload, connection=binding)
            return
        if event.event_type in {"user_text", "user_image"}:
            update_model_types(binding, event.payload)
        result = await self._receive(binding, event)
        self._respond(binding, event, result)

    @staticmethod
    def _respond(binding, event, result):
        if result is _ChatEventAcceptance.UNSUPPORTED:
            return
        if isinstance(result, VoiceUploadAck):
            ack(binding, event, payload=result.payload, duplicate=result.duplicate)
        elif isinstance(result, dict):
            binding.enqueue(encode_message(result))
        elif isinstance(result, _EventRejection):
            reject(binding, event, result.code, result.message, result.retryable)
        elif result in {_ChatEventAcceptance.ACCEPTED, _ChatEventAcceptance.DUPLICATE}:
            ack(binding, event, duplicate=result is _ChatEventAcceptance.DUPLICATE)
        elif result is _ChatEventAcceptance.BAD_MESSAGE:
            reject(binding, event, "BAD_MESSAGE", "chat event payload is invalid", False)
        else:
            reject(binding, event, "OVERLOADED", "chat ingress queue is full", True)

    async def disconnect(self, connection: AdapterConnection) -> None:
        """移除指定连接句柄、撤销其绑定并通知生命周期管理器；重复断开无副作用。"""
        binding = self._bindings.pop(connection, None)
        if binding is not None:
            if self._client_executor is not None:
                self._client_executor.clear_user(binding.user_uuid, binding)
            await complete_owned(self._close_connection(binding))

    async def close(self) -> None:
        """等待 Adapter 自有的关闭操作完成，清理连接与投递任务。"""
        await complete_owned(self._close())

    async def _close(self) -> None:
        self._closed = True
        for connection in tuple(self._bindings):
            await self.disconnect(connection)

    async def _open(self, connection: Binding, character_id: str) -> ChatStage:
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

    async def _close_connection(self, connection: Binding) -> None:
        connection.mark_disconnected()
        if connection.stage is not None:
            await self.detach_stage_binding(connection.stage, connection)
        if self._stage_manager is not None:
            await self._stage_manager.disconnect(connection)

    async def _receive(
        self, connection: Binding, event: WSMessage
    ) -> _ChatEventAcceptance | _EventRejection | VoiceUploadAck | dict[str, str]:
        """统一接收普通刺激、语音上传阶段与切换命令；返回协议应答所需结果。"""
        if event.event_type == "call.switch_prepare":
            return await self._prepare_call_switch(connection, event)
        async with self._input_lock:
            return await self._try_accept_event(connection, event)

    async def _prepare_call_switch(self, connection: Binding, event: WSMessage) -> _EventRejection | dict[str, str]:
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

    def _input_suspended(self, connection: Binding) -> bool:
        return connection.accepting and connection.stage is not None and connection.stage.input_suspended

    @staticmethod
    def _supports_input(event: WSMessage) -> bool:
        """返回该协议适配器是否认识此业务输入类型。"""
        return event.event_type in _INPUT_EVENTS

    async def _try_accept_event(
        self,
        connection: Binding,
        event: WSMessage,
    ) -> _ChatEventAcceptance | _EventRejection | VoiceUploadAck:
        """校验、去重、转换并提交一条已鉴权的业务消息。"""
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
        except VoiceUploadError as error:
            return _EventRejection(error.code, error.message, error.retryable)
        except MediaResolutionError as error:
            code = error.code.value if isinstance(error.code, MediaResolutionErrorCode) else str(error.code)
            return _EventRejection(
                code=code,
                message=_MEDIA_REJECTION_MESSAGES.get(code, "图片无法读取或已损坏"),
            )
        except (KeyError, TypeError, ValueError):
            return _ChatEventAcceptance.BAD_MESSAGE
        if isinstance(accepted, VoiceUploadAck):
            return accepted
        if not accepted:
            return _ChatEventAcceptance.OVERLOADED
        self._mark_client_message_accepted(connection, event)
        return _ChatEventAcceptance.ACCEPTED

    def _is_duplicate_client_message(self, connection: Binding, event: WSMessage) -> bool:
        """查询已接纳消息的幂等记录，不提前登记当前事件。"""
        key = self._client_message_key(connection, event)
        if key is None:
            return False
        now = time.monotonic()
        self._prune_recent_client_messages(now)
        return key in self._recent_client_messages

    def _mark_client_message_accepted(self, connection: Binding, event: WSMessage) -> bool:
        """仅在所有目标 Stage 接纳事件后登记幂等记录。"""
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

    def _client_message_key(self, connection: Binding, event: WSMessage) -> str | None:
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
        binding = self._routes.get(output.interaction_id)
        if binding is None:
            raise d.SinkRejectedError("interaction is offline", code=d.SinkRejectionCode.SINK_CLOSED)
        return binding.submit_output(output)

    async def _receive_event(self, connection: Binding, event: WSMessage) -> bool | VoiceUploadAck:
        """统一处理业务输入，投递完整刺激后提交完成回执。"""
        try:
            return await self._process_and_deliver(connection, event)
        finally:
            self._voice_uploads.discard_prepared()
            # 失败和过期通知只属于原上传绑定，不得转给替换连接。
            for binding, stimulus in self._voice_uploads.take_notifications():
                binding.submit(stimulus)

    async def _process_and_deliver(self, connection: Binding, event: WSMessage) -> bool | VoiceUploadAck:
        if connection.is_closed or not connection.user_uuid:
            raise ValueError("authenticated live connection required")
        targets = input_targets(event, self._default_character_id)
        if not connection.accepting or connection.stage is None or targets != (connection.stage.character_id,):
            raise ValueError("target character is not bound to connection")
        # 异步媒体处理期间固定 Binding 身份；解绑后该对象不再恢复输入权限。
        binding = connection
        stimulus, status = await process_input(
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
                binding = status["binding"]
            if not await self._admit_input(event, stimulus, binding):
                return self._reject_input_admission(event)
            if event.event_type == "user_voice":
                await self._voice_uploads.commit(connection)
        elif status["state"] not in {"partial", "duplicate"}:
            raise RuntimeError("unknown input processing state")
        if event.event_type == "user_voice":
            return VoiceUploadAck(status.get("ack_payload", {}), status.get("duplicate", False))
        return True

    async def _admit_input(self, event: WSMessage, stimulus: d.Stimulus, binding: Binding) -> bool:
        if not binding.can_accept(stimulus):
            return False
        if isinstance(stimulus, d.ImageMessage):
            await asyncio.to_thread(materialize_input, event, stimulus, self._media_store)
        if not binding.can_accept(stimulus):
            return False
        return binding.submit(stimulus)

    @staticmethod
    def _reject_input_admission(event: WSMessage) -> bool:
        if event.event_type == "user_voice":
            raise VoiceUploadError("OVERLOADED", "chat ingress queue is full", retryable=True)
        return False

    async def detach_stage_binding(self, stage: ChatStage, connection: InteractionConnection | None = None) -> None:
        """撤销匹配的 Stage 绑定，不直接关闭其物理 WebSocket。"""
        await complete_owned(self._unbind(stage, connection))

    async def _bind(self, stage: ChatStage, connection: Binding) -> None:
        async with self._binding_lock:
            if connection.is_closed or not connection.user_uuid or connection.user_uuid != stage.user_id:
                raise ValueError("connection user does not own stage")
            if connection.stage is not None and (connection.stage is not stage or not connection.accepting):
                raise ValueError("binding already assigned to a stage")
            old = self._routes.get(stage.interaction_id)
            if old is not None:
                if old.stage is not stage:
                    raise ValueError("interaction already owned by another stage")
                if old is connection:
                    await stage.connection_changed(d.ConnectionState.CONNECTED)
                    return
                await self._disconnect(old)
            if connection.is_closed:
                raise ValueError("connection closed during binding")
            connection.attach(stage)
            self._routes[stage.interaction_id] = connection
            try:
                await stage.connection_changed(d.ConnectionState.CONNECTED)
            except BaseException:
                await self._disconnect(self._routes[stage.interaction_id])
                raise

    async def _unbind(self, stage: ChatStage, connection: Binding | None) -> None:
        async with self._binding_lock:
            binding = self._routes.get(stage.interaction_id)
            if binding is not None and binding.stage is stage and (connection is None or binding is connection):
                await self._disconnect(binding)

    async def _disconnect(self, binding) -> None:
        await binding.detach()
        self._routes.pop(binding.stage.interaction_id, None)
