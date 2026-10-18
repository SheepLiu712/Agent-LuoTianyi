"""通话接入和输出路由门面；Session 与 Binding 的内部机制不向 Web 暴露。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from src.domain.call import CallEndReason
from src.stage.call_stage import CallPCM, CallPlaybackStop, CallSetupFailed, CallStageOutput, CallStreamStarted
from src.stage.stage_manager import CallStartFailed, InteractionFinalizing, StageManager
from src.utils.owned_operation import complete_owned

from ..connection import AdapterConnection, OutboundDelivery
from ._binding import Binding
from ._protocol_translate import encode_control, parse_message
from ._session import Session
from .errors import CallTransportError


class _OutputSink:
    """保留 Stage 的类型化输出契约，所有输出经 Adapter 按 call_id 路由。"""

    def __init__(self, adapter):
        self._adapter = adapter
        self.call_id = None

    async def send_state(self, item):
        """提交通话状态或回复失败事件。"""
        await self._adapter.submit_output(self.call_id, item)

    async def send_ended(self, snapshot):
        """提交业务终态。"""
        await self._adapter.submit_output(self.call_id, snapshot)

    async def send_failed(self, reason):
        """提交建立失败原因。"""
        await self._adapter.submit_output(self.call_id, CallSetupFailed(reason))

    async def start_stream(self, response_id, stream_id, audio_format):
        """提交音频流开始，不分配传输序号。"""
        await self._adapter.submit_output(self.call_id, CallStreamStarted(response_id, stream_id, audio_format))

    async def send_pcm(self, response_id, stream_id, payload, *, final):
        """提交音频内容及流末尾标记。"""
        await self._adapter.submit_output(self.call_id, CallPCM(response_id, stream_id, payload, final))

    async def stop_response(self, response_id, stream_ids):
        """提交业务取消意图，序号范围由 Delivery 计算。"""
        await self._adapter.submit_output(self.call_id, CallPlaybackStop(response_id, stream_ids))


@dataclass(frozen=True, slots=True)
class CallCapabilityStatus:
    """汇总启用条件和可接入角色，供能力查询与正式接入共同使用。"""

    enabled: bool
    trusted_host: bool
    provider_ready: bool
    call_tts_ready: bool
    summary_ready: bool
    settlement_ready: bool
    stage_binding_ready: bool
    recovery_ready: bool
    character_ids: tuple[str, ...] = ()

    @property
    def available(self) -> bool:
        """判断通话所有必需能力是否就绪。"""
        return all(
            (
                self.enabled,
                self.trusted_host,
                self.provider_ready,
                self.call_tts_ready,
                self.summary_ready,
                self.settlement_ready,
                self.stage_binding_ready,
                self.recovery_ready,
                bool(self.character_ids),
            )
        )


class CallWebSocketAdapter:
    """管理通话 Session 和连接 Binding，统一提供网络入口与输出路由。"""

    def __init__(
        self,
        *,
        manager: StageManager,
        user_reset_fence=None,
        call_metrics=None,
        enabled=False,
        trusted_host=True,
        provider_ready=True,
        call_tts_character_ids=None,
        call_summary_character_ids=None,
        supports_character=None,
    ):
        self._manager = manager
        self._user_reset_fence = user_reset_fence
        self._call_metrics = call_metrics
        self._enabled = enabled
        self._trusted_host = trusted_host
        self._provider_ready = provider_ready
        self._call_tts_character_ids = call_tts_character_ids
        self._call_summary_character_ids = call_summary_character_ids
        self._supports_character = supports_character
        self._sessions = {}
        self._bindings = {}
        self._start_locks = {}
        self._open_tasks = set()
        self._open_cancellations = {}
        self._release_tasks = set()
        self._closed = False

    @property
    def capability_status(self) -> CallCapabilityStatus:
        """返回通话接入所需能力的当前事实。"""
        tts_ids = tuple(self._call_tts_character_ids()) if self._call_tts_character_ids is not None else ()
        summary_ids = tuple(self._call_summary_character_ids()) if self._call_summary_character_ids is not None else ()
        character_ids = tuple(character_id for character_id in tts_ids if character_id in frozenset(summary_ids))
        legacy_ready = self._supports_character is not None
        if legacy_ready and not character_ids:
            character_ids = ("*",)
        return CallCapabilityStatus(
            enabled=self._enabled,
            trusted_host=self._trusted_host,
            provider_ready=self._provider_ready,
            call_tts_ready=bool(tts_ids) or legacy_ready,
            summary_ready=bool(summary_ids) or legacy_ready,
            settlement_ready=self._manager.call_settlement_ready or legacy_ready,
            stage_binding_ready=not self._closed and not self._manager.is_closed(),
            recovery_ready=self._manager.call_recovery_ready or legacy_ready,
            character_ids=character_ids,
        )

    def supports_call_character(self, character_id: str) -> bool:
        """判断指定角色当前是否允许建立通话。"""
        status = self.capability_status
        if self._supports_character is not None:
            return status.available and self._supports_character(character_id)
        return status.available and character_id in status.character_ids

    async def open(
        self,
        *,
        user_id: str,
        connection_id: object,
        character_id: str | None = None,
        initial_message: str | bytes | None = None,
        capabilities: frozenset[str] = frozenset(),
    ) -> AdapterConnection:
        """取得 PREPARING Stage 或原呼叫，建立唯一连接并排队握手。"""
        if not isinstance(initial_message, str):
            raise CallTransportError("CALL_START_REQUIRED")
        if self._closed or not self.capability_status.available:
            raise CallTransportError("CALL_INGRESS_UNAVAILABLE", close_code=1013)
        frame = parse_message(initial_message)
        if frame.control["type"] not in {"call.start", "call.resume"}:
            raise CallTransportError("CALL_START_REQUIRED")
        cancelled = asyncio.Event()
        task = asyncio.create_task(self._open_owned(frame, user_id, connection_id, cancelled), name="call-adapter-open")
        self._open_tasks.add(task)
        self._open_cancellations[task] = cancelled
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled.set()
            try:
                handle = await complete_owned(self._await_open(task))
            except BaseException:
                pass
            else:
                await complete_owned(self.disconnect(handle))
            raise
        finally:
            self._open_tasks.discard(task)
            self._open_cancellations.pop(task, None)

    async def _open_owned(self, frame, user_id, connection_id, cancelled):
        generation = None
        if self._user_reset_fence is not None:
            generation = await self._user_reset_fence.track_current(user_id)
        if frame.control["type"] == "call.resume":
            return await self._open_resume(frame, user_id, connection_id, cancelled, generation)
        key = str(frame.control["client_request_id"])
        lock, users = self._start_locks.get(key, (asyncio.Lock(), 0))
        self._start_locks[key] = lock, users + 1
        try:
            async with lock:
                return await self._open_start(frame, user_id, connection_id, cancelled, generation)
        finally:
            _, users = self._start_locks[key]
            if users == 1:
                self._start_locks.pop(key)
            else:
                self._start_locks[key] = lock, users - 1

    @staticmethod
    async def _await_open(task):
        return await asyncio.shield(task)

    async def _open_start(self, frame, user_id, connection_id, cancelled, generation):
        message = frame.control
        request_id, character_id = str(message["client_request_id"]), str(message["character_id"])
        if frame.seq != 1:
            raise CallTransportError("CALL_START_REQUIRED")
        if not self.supports_call_character(character_id):
            raise self._start_error("CALL_CHARACTER_UNAVAILABLE", request_id, frame.seq, close_code=1008)
        stage = session = binding = None
        created = False
        try:
            sink = _OutputSink(self)
            stage = await self._manager.try_to_get_stage(
                stage_type="call",
                user_id=user_id,
                character_id=character_id,
                client_request_id=request_id,
                transport=sink,
            )
            sink.call_id = stage.call_id
            session = self._sessions.get(stage.call_id)
            if session is None:
                created = True
                session = Session(stage, call_metrics=self._call_metrics)
                self._sessions[stage.call_id] = session
            binding = Binding(session, connection_id=connection_id)
            await session.attach(binding)
            await self._validate_open(user_id, generation, cancelled)
            await binding.receive(frame)
            await self._validate_open(user_id, generation, cancelled)
            handle = self._register_binding(binding)
            if created:
                self._own_release(stage, session)
            stage.begin_initialization()
            return handle
        except BaseException as error:
            if binding is not None:
                await complete_owned(session.detach(binding))
            if created:
                try:
                    await complete_owned(stage.abort_failed_start())
                finally:
                    await self._remove_session(session)
            if isinstance(error, asyncio.CancelledError):
                raise
            if isinstance(error, CallTransportError):
                raise self._start_error(error.code, request_id, frame.seq, close_code=error.close_code) from error
            raise self._normalize_start_error(error, request_id, frame.seq) from error

    async def _open_resume(self, frame, user_id, connection_id, cancelled, generation):
        message = frame.control
        session = self._sessions.get(str(message["call_id"]))
        if session is None:
            raise CallTransportError("CALL_NOT_FOUND", close_code=1008)
        if session.user_id != user_id or session.character_id != message["character_id"]:
            raise CallTransportError("RESUME_OWNERSHIP_MISMATCH", close_code=1008)
        try:
            stage = await self._manager.try_to_get_stage(
                stage_type="call", user_id=user_id, character_id=session.character_id, call_id=session.call_id
            )
        except RuntimeError as error:
            raise CallTransportError(str(error), close_code=1008) from error
        binding = Binding(session, connection_id=connection_id)
        committed = False
        try:
            await self._validate_open(user_id, generation, cancelled)
            await session.attach(binding, resume_cursor=int(message["last_contiguous_server_seq"]))
            committed = True
            await self._validate_open(user_id, generation, cancelled)
            return self._register_binding(binding)
        except BaseException:
            await complete_owned(session.detach(binding))
            if committed:
                await complete_owned(stage.terminate(CallEndReason.SYSTEM_FAILURE))
                await self._remove_session(session)
            raise

    async def _validate_open(self, user_id, generation, cancelled):
        if cancelled.is_set() or self._closed:
            raise asyncio.CancelledError
        if generation is not None:
            await self._user_reset_fence.require_generation(user_id, generation)

    def _register_binding(self, binding):
        for handle, old in tuple(self._bindings.items()):
            if old.session is binding.session:
                old.invalidate()
                self._bindings.pop(handle)
        handle = AdapterConnection()
        self._bindings[handle] = binding
        return handle

    async def receive(self, connection: AdapterConnection, message: str | bytes) -> None:
        """解析原始帧，将会话输入交给当前 Binding。"""
        await self._binding(connection).receive(parse_message(message))

    async def next_output(self, connection: AdapterConnection) -> OutboundDelivery:
        """取得本次连接的下一个网络发送任务。"""
        return await self._binding(connection).next_output()

    def complete_output(
        self, connection: AdapterConnection, delivery_id: str, *, error: Exception | None = None
    ) -> None:
        """反馈本次网络发送结果，旧连接反馈不影响新 Binding。"""
        binding = self._bindings.get(connection)
        if binding is not None:
            binding.complete_output(delivery_id, error=error)

    async def disconnect(self, connection: AdapterConnection) -> None:
        """撤销连接，Session 与 Delivery 在业务恢复期限内保留。"""
        binding = self._bindings.pop(connection, None)
        if binding is not None:
            await complete_owned(binding.session.detach(binding))

    async def submit_output(self, call_id: str, output: CallStageOutput) -> None:
        """按稳定呼叫身份路由输出，Stage 无需持有或替换连接 Binding。"""
        session = self._sessions.get(call_id)
        if session is None:
            raise CallTransportError("CALL_SESSION_UNAVAILABLE", close_code=1013)
        await session.submit_output(output)

    def _binding(self, handle):
        binding = self._bindings.get(handle)
        if binding is None or binding.is_closed:
            raise CallTransportError("STALE_CALL_CONNECTION", close_code=1008)
        return binding

    def _own_release(self, stage, session):
        task = asyncio.create_task(self._release_terminal(stage, session), name="call-adapter-release")
        self._release_tasks.add(task)
        task.add_done_callback(self._release_tasks.discard)
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())

    async def _release_terminal(self, stage, session):
        await stage.wait_closed()
        try:
            await session.drain_terminal()
        finally:
            await self._remove_session(session)

    async def _remove_session(self, session):
        if self._sessions.get(session.call_id) is session:
            self._sessions.pop(session.call_id)
        await session.close()
        for handle, binding in tuple(self._bindings.items()):
            if binding.session is session:
                self._bindings.pop(handle)

    async def close(self) -> None:
        """关闭接入并释放所有协议资源，不接管 Stage 的认知收尾。"""
        await complete_owned(self._close())

    async def _close(self):
        self._closed = True
        for cancelled in self._open_cancellations.values():
            cancelled.set()
        await asyncio.gather(*tuple(self._open_tasks), return_exceptions=True)
        for handle in tuple(self._bindings):
            await self.disconnect(handle)
        for session in tuple(self._sessions.values()):
            await self._remove_session(session)
        for task in tuple(self._release_tasks):
            task.cancel()
        await asyncio.gather(*tuple(self._release_tasks), return_exceptions=True)

    @staticmethod
    def _start_error(
        code: str,
        request_id: str,
        request_seq: int,
        *,
        retryable: bool = False,
        call_id: str | None = None,
        close_code: int = 1013,
    ) -> CallTransportError:
        error = CallTransportError(code, close_code=close_code)
        error.request_id = request_id
        error.request_seq = request_seq
        error.retryable = retryable
        error.call_id = call_id
        error.initial_message = encode_control(
            {
                "protocol": "call.v1",
                "type": "error",
                "code": error.code,
                "message": "call start was not accepted",
                "retryable": retryable,
                "request_type": "call.start",
                "request_seq": request_seq,
                "client_request_id": request_id,
                **({} if call_id is None else {"call_id": call_id}),
            },
        ).text
        return error

    @classmethod
    def _normalize_start_error(cls, error: Exception, request_id: str, request_seq: int) -> CallTransportError:
        if isinstance(error, InteractionFinalizing):
            return cls._start_error("INTERACTION_FINALIZING", request_id, request_seq, retryable=True)
        if isinstance(error, CallStartFailed):
            return cls._start_error("CALL_START_FAILED", request_id, request_seq, call_id=error.call_id)
        if isinstance(error, TimeoutError):
            return cls._start_error("CALL_START_TIMEOUT", request_id, request_seq, retryable=True)
        if str(error) in {
            "USER_DATA_RESET_IN_PROGRESS",
            "USER_DATA_RESET_INVALIDATED_OPERATION",
            "STAGE_MANAGER_CLOSED",
        }:
            return cls._start_error("CALL_START_UNAVAILABLE", request_id, request_seq, retryable=True)
        if isinstance(error, ValueError):
            return cls._start_error("CALL_START_REJECTED", request_id, request_seq)
        return cls._start_error("CALL_START_FAILED", request_id, request_seq)
