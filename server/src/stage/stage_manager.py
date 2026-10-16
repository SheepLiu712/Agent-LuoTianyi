"""管理聊天、通话的接入、占用及收尾任务。"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol
from uuid import uuid4

from src.agent.context import ContextFactory
from src.domain.agent import InteractionEndingReason
from src.domain.call import CallEndReason, CallState
from src.domain.stage import StageState
from src.domain.stage.due_events import DueEventProvider
from src.infrastructure.persistence.call_sessions import (
    BEIJING_TIMEZONE,
    CallSessionRecord,
    CallSessionRepository,
)
from src.utils.logger import get_logger
from src.utils.owned_operation import complete_owned

from ._finalization import (
    CallFinalizationSink,
    FinalizationTasks,
    InteractionFinalizing,
)
from .call_settlement import (
    CallAgentSettlement,
    CallSettlement,
    CallSettlementConsumerImpl,
    StaleCallRecoveryService,
)
from .chat_stage import ChatStage
from .interaction_lease import (
    CallTransitionIntent,
    CallTransitionOwnership,
    InteractionLease,
    InteractionLeaseRegistry,
    InteractionSource,
)

if TYPE_CHECKING:
    from src.adapter.websocket import WebSocketAdapter
    from src.agent.facade import Agent
    from src.infrastructure.models.realtime_speech import RealtimeSpeechSessionFactory
    from src.infrastructure.observability.call_metrics import CallMetrics
    from src.infrastructure.persistence.call_maintenance import (
        SqlCallMaintenanceBatchRepository,
    )
    from src.infrastructure.persistence.database.services.conversation_service import (
        ConversationService,
    )
    from src.stage.call_stage import CallStage, CallTransportSink
    from src.web.websocket.service import WebSocketConnection


@dataclass(frozen=True)
class _ManagerConfig:
    offline_timeout: float
    return_user_threshold_seconds: float
    call_setup_timeout: float

    @classmethod
    def from_dict(cls, config: dict) -> _ManagerConfig:
        if not isinstance(config, dict):
            raise TypeError("stage manager config must be a dictionary")
        timeout = config.get("offline_timeout", 60.0)
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout < 0:
            raise ValueError("offline_timeout must be finite and nonnegative")
        return_threshold = config.get("return_user_threshold_seconds", 5 * 24 * 60 * 60)
        if type(return_threshold) not in (int, float) or not math.isfinite(return_threshold) or return_threshold <= 0:
            raise ValueError("return_user_threshold_seconds must be positive and finite")
        call_setup_timeout = config.get("call_setup_timeout", 10.0)
        if (
            type(call_setup_timeout) not in (int, float)
            or not math.isfinite(call_setup_timeout)
            or call_setup_timeout <= 0
        ):
            raise ValueError("call_setup_timeout must be positive and finite")
        return cls(
            offline_timeout=timeout,
            return_user_threshold_seconds=return_threshold,
            call_setup_timeout=call_setup_timeout,
        )


@dataclass(frozen=True, slots=True)
class CallStartClaim:
    record: CallSessionRecord
    lease: InteractionLease
    duplicate: bool
    setup_deadline: float
    admission_generation: int = 0


@dataclass(frozen=True, slots=True)
class CallStageOwnership:
    call_id: str
    user_id: str
    character_id: str
    client_request_id: str
    setup_deadline: float
    generation: int


@dataclass(frozen=True, slots=True)
class CallOpenRequest:
    user_id: str
    character_id: str
    client_request_id: str
    source_interaction_id: str | None = None


@dataclass(frozen=True, slots=True)
class CallIdentity:
    call_id: str
    client_request_id: str
    character_id: str
    state: CallState


class CallOpenTransport(Protocol):
    async def prepare(self, identity: CallIdentity) -> None: ...

    async def abort_prepare(self) -> None: ...

    def bind_stage(self, stage: CallStage) -> None: ...


class CallControl:
    """Finite business control for one accepted call; transport internals stay hidden."""

    def __init__(
        self,
        manager: StageManager,
        request: CallOpenRequest,
        transport: CallOpenTransport,
    ) -> None:
        self._manager = manager
        self._request = request
        self._transport_sink = transport
        self._identity: CallIdentity | None = None
        self._stage: CallStage | None = None
        self._connected = True
        self._termination_reason: CallEndReason | None = None
        self._setup_task: asyncio.Task | None = None
        self._stage_available = asyncio.Event()
        self._ready = asyncio.Event()

    def release(self) -> None:
        """Allow the accepted transport handshake to begin business setup exactly once."""
        if self._setup_task is None:
            self._setup_task = asyncio.create_task(
                self._manager._establish_open_call(self),
                name=f"call-open-establish-{self.identity.call_id}",
            )

    @property
    def identity(self) -> CallIdentity:
        if self._identity is None:
            raise RuntimeError("call identity is not prepared")
        return self._identity

    async def disconnect(self) -> None:
        self._connected = False
        if self._stage is not None:
            await self._stage.set_connection_available(False)

    async def resume(self) -> bool:
        if self._stage is None:
            return self._setup_task is not None and not self._setup_task.done()
        if self._stage.state in {CallState.PREPARING, CallState.RINGING}:
            return True
        return self._stage.can_resume()

    async def commit_resume(self) -> bool:
        self._connected = True
        if self._stage is None:
            return self._setup_task is not None and not self._setup_task.done()
        if self._stage.state in {CallState.PREPARING, CallState.RINGING}:
            await self._stage.set_connection_available(True)
            return True
        return await self._stage.resume()

    async def terminate(self, reason: CallEndReason = CallEndReason.USER_HANGUP):
        if self._termination_reason is None:
            self._termination_reason = reason
        if self._stage is None and self._setup_task is not None and not self._setup_task.done():
            await self._stage_available.wait()
        if self._stage is None:
            if self._setup_task is not None:
                await asyncio.shield(self._setup_task)
        if self._stage is None:
            return None
        return await self._stage.terminate(self._termination_reason)

    async def wait_realtime_stopped(self):
        await self._ready.wait()
        if self._stage is None:
            return None
        return await self._stage.wait_closed()


class CallStartFailed(RuntimeError):
    """Stable duplicate-start failure preserving the durable call identity."""

    def __init__(self, record: CallSessionRecord) -> None:
        self.call_id = str(record.call_id)
        self.end_reason = record.end_reason
        super().__init__("CALL_START_FAILED")


class InteractionOwnedByCallAdmission(RuntimeError):
    """Chat admission was rejected because call ownership is current."""

    def __init__(self, source: InteractionSource) -> None:
        self.source = source
        super().__init__("INTERACTION_OWNED_BY_CALL")


class StageManager:
    """按用户与角色管理 Stage，统一持有 Chat / Call 收尾与重置接入占用。"""

    def __init__(
        self,
        *,
        get_agent: Callable[[str], Agent],
        adapter: WebSocketAdapter,
        get_context_factory: Callable[[str], ContextFactory],
        due_event_provider: DueEventProvider | None = None,
        lease_registry: InteractionLeaseRegistry | None = None,
        call_sessions: CallSessionRepository | None = None,
        conversation_service: ConversationService | None = None,
        call_maintenance_batches: SqlCallMaintenanceBatchRepository | None = None,
        call_metrics: CallMetrics | None = None,
        realtime_speech_factory: RealtimeSpeechSessionFactory | None = None,
        recovery_projection_verifier: Any | None = None,
        user_reset_fence: Any | None = None,
        wall_clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        config: dict | None = None,
    ) -> None:
        """使用 get_agent 与 get_context_factory 取得角色门面和上下文创建依赖。

        config.offline_timeout 为离线保留秒数，stage 子配置直接下传。
        """
        config = {} if config is None else config
        self._config = _ManagerConfig.from_dict(config)
        self._stage_config = config.get("stage", {})
        self._get_agent, self._adapter = get_agent, adapter
        self._get_context_factory = get_context_factory
        self._due_event_provider = due_event_provider
        self._lease_registry = lease_registry or InteractionLeaseRegistry()
        self._call_sessions = call_sessions
        self._realtime_speech_factory = realtime_speech_factory
        self._call_metrics = call_metrics
        self._stale_call_recovery = (
            StaleCallRecoveryService(
                call_sessions=call_sessions,
                conversation_service=conversation_service,
                call_maintenance_batches=call_maintenance_batches,
                projection_verifier=recovery_projection_verifier,
            )
            if recovery_projection_verifier is not None
            else None
        )
        self._initialization: asyncio.Task[None] | None = None
        self._recovery_ready = recovery_projection_verifier is None
        self._user_reset_fence = user_reset_fence
        self._wall_clock = wall_clock or (lambda: datetime.now(BEIJING_TIMEZONE))
        self._monotonic = monotonic
        self._last_call_timestamp: datetime | None = None
        self._time_lock = asyncio.Lock()
        self._stages: dict[tuple[str, str], ChatStage] = {}
        self._connections: dict[ChatStage, WebSocketConnection] = {}
        self._expiry: dict[ChatStage, asyncio.Task[None]] = {}
        self._finalizations = FinalizationTasks()
        self._call_settlement = (
            CallSettlement(
                consumer=CallSettlementConsumerImpl(
                    agent_settlement=CallAgentSettlement(
                        get_agent=get_agent,
                        get_context_factory=get_context_factory,
                    ),
                    call_sessions=call_sessions,
                    conversation_service=conversation_service,
                    call_maintenance_batches=call_maintenance_batches,
                    call_metrics=call_metrics,
                ),
            )
            if call_sessions is not None and conversation_service is not None and call_maintenance_batches is not None
            else None
        )
        self._lock = asyncio.Lock()
        self._closed = False
        self._closing: asyncio.Task[None] | None = None
        self._pending_first_logins: set[tuple[str, str]] = set()
        self._pending_regular_logins: set[tuple[str, str]] = set()
        self._call_starts: dict[str, asyncio.Task[CallStartClaim]] = {}
        self._call_start_operations: dict[str, tuple[str, str, str | None]] = {}
        self._call_setup_deadlines: dict[str, float] = {}
        self._call_claims: dict[str, CallStartClaim] = {}
        self._call_ownerships: dict[str, CallStageOwnership] = {}
        self._call_stages: dict[str, CallStage] = {}
        self._call_controls: dict[str, CallControl] = {}
        self._call_controls_by_request: dict[str, CallControl] = {}
        self._call_open_tasks: dict[str, asyncio.Task[CallControl]] = {}
        self._call_stage_creations: set[asyncio.Task[Any]] = set()
        self._call_stage_creation_users: dict[asyncio.Task[Any], str] = {}
        self._call_ownership_generation = 0
        self._intent_expiry: dict[tuple[str, str], asyncio.Task[None]] = {}

    @property
    def call_settlement_ready(self) -> bool:
        return bool(self._call_settlement and self._call_settlement.is_ready)

    @property
    def call_recovery_ready(self) -> bool:
        return self._recovery_ready

    @property
    def call_business_ready(self) -> bool:
        return not self._closed and (
            self._stale_call_recovery is None or (self.call_settlement_ready and self.call_recovery_ready)
        )

    async def initialize(self) -> None:
        """Recover durable call state exactly once before opening call admission."""
        if self._closed:
            raise RuntimeError("stage manager closed during initialization")
        if self._recovery_ready:
            return
        if self._initialization is None:
            self._initialization = asyncio.create_task(self._initialize(), name="stage-manager-initialize")
            self._initialization.add_done_callback(self._observe_initialization)
        await complete_owned(self._await_initialization(self._initialization))

    async def _initialize(self) -> None:
        if self._stale_call_recovery is None:
            raise RuntimeError("stale call recovery is not configured")
        report = await self._stale_call_recovery.reconcile()
        if report.failed or report.conflicted:
            raise RuntimeError("stale call recovery did not converge")
        if self._closed:
            raise RuntimeError("stage manager closed during initialization")
        self._recovery_ready = True

    @staticmethod
    def _observe_initialization(task: asyncio.Task[None]) -> None:
        if not task.cancelled():
            task.exception()

    @staticmethod
    async def _await_initialization(task: asyncio.Task[None]) -> None:
        await asyncio.shield(task)

    async def open_call(self, request: CallOpenRequest, transport: CallOpenTransport) -> CallControl:
        """Accept one call identity and retain its background establishment operation."""
        if not self.call_business_ready:
            raise RuntimeError("CALL_INGRESS_UNAVAILABLE")
        request = replace(
            request,
            source_interaction_id=await self._infer_call_source_interaction(
                user_id=request.user_id, character_id=request.character_id
            ),
        )
        existing = await self._find_call_by_request(
            request.client_request_id,
            user_id=request.user_id,
            character_id=request.character_id,
        )
        if existing is not None:
            return existing
        task = self._call_open_tasks.get(request.client_request_id)
        if task is None:
            task = asyncio.create_task(
                self._open_call(request, transport),
                name=f"call-open-{request.client_request_id}",
            )
            self._call_open_tasks[request.client_request_id] = task
            task.add_done_callback(lambda done, key=request.client_request_id: self._observe_open_call(key, done))
        control = await asyncio.shield(task)
        if control._request != request:
            raise ValueError("client_request_id is already starting another call")
        return control

    async def _open_call(self, request: CallOpenRequest, transport: CallOpenTransport) -> CallControl:
        if self._realtime_speech_factory is None:
            raise RuntimeError("realtime speech factory is not bound")
        control = CallControl(self, request, transport)
        self._call_controls_by_request[request.client_request_id] = control
        try:
            start = asyncio.create_task(
                self._claim_call(
                    user_id=request.user_id,
                    character_id=request.character_id,
                    source_interaction_id=request.source_interaction_id,
                    client_request_id=request.client_request_id,
                ),
                name=f"call-open-claim-{request.client_request_id}",
            )
            claim = await asyncio.shield(start)
            record = claim.record
            identity = CallIdentity(
                str(record.call_id),
                request.client_request_id,
                request.character_id,
                CallState.PREPARING,
            )
            control._identity = identity
            self._call_controls[identity.call_id] = control
            try:
                await transport.prepare(identity)
            except BaseException as error:
                await transport.abort_prepare()
                await self._fail_pending_call_claim(claim, error)
                raise
            control._claim = claim
            return control
        except BaseException:
            self._call_controls_by_request.pop(request.client_request_id, None)
            if control._identity is not None:
                self._call_controls.pop(control._identity.call_id, None)
            raise

    def _observe_open_call(self, request_id: str, task: asyncio.Task[CallControl]) -> None:
        if self._call_open_tasks.get(request_id) is task:
            self._call_open_tasks.pop(request_id, None)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            get_logger(__name__).error("Call open failed request=%s type=%s", request_id, type(error).__name__)

    async def resume_call(self, call_id: str, *, user_id: str, character_id: str) -> CallControl:
        control = self._call_controls.get(call_id)
        if control is None:
            raise RuntimeError("CALL_NOT_FOUND")
        if control._request.user_id != user_id or control.identity.character_id != character_id:
            raise RuntimeError("RESUME_OWNERSHIP_MISMATCH")
        if not await control.resume():
            raise RuntimeError("CALL_RESUME_UNAVAILABLE")
        return control

    async def commit_call_resume(self, control: CallControl) -> None:
        if self._call_controls.get(control.identity.call_id) is not control or not await control.commit_resume():
            raise RuntimeError("CALL_RESUME_UNAVAILABLE")

    async def _find_call_by_request(
        self, client_request_id: str, *, user_id: str, character_id: str
    ) -> CallControl | None:
        task = self._call_open_tasks.get(client_request_id)
        if task is not None:
            control = await asyncio.shield(task)
            if control._request.user_id != user_id or control.identity.character_id != character_id:
                raise ValueError("client_request_id belongs to another call owner")
            return control
        control = self._call_controls_by_request.get(client_request_id)
        if control is not None:
            if control._request.user_id != user_id or control.identity.character_id != character_id:
                raise ValueError("client_request_id belongs to another call owner")
            return control
        if self._call_sessions is None:
            return None
        record = await self._repository_call(self._call_sessions.find_by_request, client_request_id)
        if record is None:
            return None
        if record.user_id != user_id or record.character_id != character_id:
            raise ValueError("client_request_id belongs to another call owner")
        raise CallStartFailed(record)

    async def abort_open_call(self, control: CallControl, error: BaseException) -> None:
        """Compensate a prepared call whose initial ACK was not committed."""
        claim = getattr(control, "_claim", None)
        if claim is not None:
            await self._fail_pending_call_claim(claim, error)
        self._call_controls.pop(control.identity.call_id, None)
        if self._call_controls_by_request.get(control._request.client_request_id) is control:
            self._call_controls_by_request.pop(control._request.client_request_id, None)

    async def _establish_open_call(self, control: CallControl) -> None:
        claim = getattr(control, "_claim", None)
        if claim is None:
            control._stage_available.set()
            control._ready.set()
            return
        try:
            stage = await self._create_call_stage(
                claim,
                user_id=control._request.user_id,
                character_id=control._request.character_id,
                client_request_id=control._request.client_request_id,
                speech_factory=self._realtime_speech_factory,
                transport=control._transport_sink,
                call_metrics=self._call_metrics,
                stage_created=lambda stage: self._publish_control_stage(control, stage),
                connection_available=control._connected,
            )
            self._publish_control_stage(control, stage)
            if control._termination_reason is not None:
                await stage.terminate(control._termination_reason)
        except BaseException as error:
            get_logger(__name__).error(
                "Call establishment failed request=%s type=%s error=%s",
                control._request.client_request_id,
                type(error).__name__,
                error,
            )
        finally:
            control._stage_available.set()
            control._ready.set()

    @staticmethod
    def _publish_control_stage(control: CallControl, stage: CallStage) -> None:
        control._stage = stage
        control._stage_available.set()

    def current_call_control(self, call_id: str) -> CallControl | None:
        return self._call_controls.get(call_id)

    def _start_call_finalization(self, ownership, snapshot, context) -> None:
        self._finalizations.start(
            ownership.call_id,
            (ownership.user_id, ownership.character_id),
            lambda: self._finalize_call(ownership, snapshot, context),
        )

    def _start_call_termination(self, stage, ownership, reason) -> asyncio.Task:
        return self._finalizations.start_termination(
            ownership.call_id,
            (ownership.user_id, ownership.character_id),
            lambda: stage._terminate_owned(reason),
        )

    async def _finalize_call(self, ownership, snapshot, context) -> None:
        settlement_error: BaseException | None = None
        try:
            if self._call_settlement is None:
                raise RuntimeError("call settlement is not configured")
            await self._call_settlement.settle(snapshot, context=context)
        except BaseException as error:
            settlement_error = error
        finally:
            try:
                if context is not None:
                    await complete_owned(context.close())
            except BaseException as close_error:
                if settlement_error is None:
                    settlement_error = close_error
                else:
                    self._report_call_context_close_failure(ownership, settlement_error, close_error)
            finally:
                self._release_call_stage_ownership(ownership)
                self._call_controls.pop(ownership.call_id, None)
                self._call_controls_by_request.pop(ownership.client_request_id, None)
        if settlement_error is not None:
            raise settlement_error

    @staticmethod
    def _report_call_context_close_failure(ownership, settlement_error, close_error) -> None:
        try:
            get_logger(__name__).error(
                "Call context close failed call=%s settlement_type=%s close_type=%s",
                ownership.call_id,
                type(settlement_error).__name__,
                type(close_error).__name__,
            )
        except Exception:
            pass

    async def begin_user_data_reset(self, user_id: str) -> object:
        async with self._lock:
            if self._closed:
                raise RuntimeError("STAGE_MANAGER_CLOSED")
            if self._user_has_interactions(user_id):
                raise RuntimeError("USER_INTERACTION_BUSY")
            if self._user_reset_fence is None:
                raise RuntimeError("user reset fence is not configured")
            return await self._user_reset_fence.begin_if_idle(user_id)

    async def end_user_data_reset(self, user_id: str, token: object) -> None:
        await self._user_reset_fence.end(user_id, token)

    def _user_has_interactions(self, user_id: str) -> bool:
        return (
            self._finalizations.has_user(user_id)
            or any(owner == user_id for owner, _ in self._stages)
            or any(owner.user_id == user_id for owner in self._call_ownerships.values())
            or any(claim.record.user_id == user_id for claim in self._call_claims.values())
            or any(owner[0] == user_id for owner in self._call_start_operations.values())
            or any(owner == user_id and not task.done() for task, owner in self._call_stage_creation_users.items())
        )

    def record_login(
        self,
        user_id: str,
        character_id: str,
        *,
        elapsed_from_last_login: float | None,
    ) -> bool:
        """记录目标角色的认证登录；返回是否由 Stage 主动链接管。"""
        if any(not isinstance(value, str) or not value.strip() for value in (user_id, character_id)):
            raise ValueError("user_id and character_id must be nonblank")
        if elapsed_from_last_login is None:
            key = (user_id, character_id)
            stage = self._stages.get(key)
            if stage is not None and stage.state is StageState.ONLINE:
                stage.schedule_first_login()
            else:
                self._pending_first_logins.add(key)
            return True
        now = time.localtime()
        seconds_since_midnight = now.tm_hour * 3600 + now.tm_min * 60 + now.tm_sec
        if seconds_since_midnight <= elapsed_from_last_login < self._config.return_user_threshold_seconds:
            key = (user_id, character_id)
            stage = self._stages.get(key)
            if stage is not None and stage.state is StageState.ONLINE:
                stage.schedule_login_reminders()
            else:
                self._pending_regular_logins.add(key)
            return True
        return False

    async def scan_due_events(self) -> int:
        """唤醒在线 Stage；每个 Stage 自行执行空闲检查与单项选择。"""
        async with self._lock:
            stages = tuple(self._connections)
        sent = 0
        for stage in stages:
            sent += int(await stage.dispatch_due_events(merge_all=False))
        return sent

    async def propose_relationship(self, user_id: str, relationship: str) -> int:
        """将已保存的关系提议投递给用户当前及离线保留中的全部 Stage。"""
        async with self._lock:
            stages = tuple(
                stage
                for (owner_id, _), stage in self._stages.items()
                if owner_id == user_id and stage.state not in (StageState.TERMINATING, StageState.TERMINATED)
            )
            for stage in stages:
                await stage.propose_relationship(relationship)
            return len(stages)

    async def connect(self, connection: WebSocketConnection, character_id: str) -> ChatStage:
        """取得或创建 connection 用户与 character_id 的 Stage，完成绑定后返回；保留期内复用原实例。"""
        return await complete_owned(self._connect(connection, character_id))

    async def disconnect(self, connection: WebSocketConnection) -> None:
        """处理 connection 断线，解除其仍有效的绑定并启动离线保留期；旧连接通知不影响重连。"""
        await complete_owned(self._disconnect(connection))

    async def close(self) -> None:
        """停止接入，终止全部 Stage 并解除绑定，等待正在执行的离线回收任务。"""
        if self._closing is None:
            self._closing = asyncio.create_task(self._close(), name="stage-manager-close")
        await asyncio.shield(self._closing)

    def is_closed(self) -> bool:
        return self._closed

    async def _connect(self, connection: WebSocketConnection, character_id: str) -> ChatStage:
        async with self._lock:
            if self._user_reset_fence is not None:
                await self._user_reset_fence.track_current(connection.user_uuid)
            if self._closed or connection.is_closed or not connection.user_uuid:
                raise ValueError("manager or connection is unavailable")
            key = (connection.user_uuid, character_id)
            self._require_chat_admission(key)
            stage = self._stages.get(key)
            if stage is None or stage.state in (
                StageState.TERMINATING,
                StageState.TERMINATED,
            ):
                if stage is not None:
                    self._lease_registry.release(
                        InteractionLease(
                            stage.user_id,
                            stage.character_id,
                            stage.interaction_id,
                            InteractionSource.CHAT,
                        )
                    )
                stage = await ChatStage.create(
                    user_id=key[0],
                    character_id=key[1],
                    agent=self._get_agent(character_id),
                    adapter=self._adapter,
                    config=self._stage_config,
                    context_factory=self._get_context_factory(character_id),
                    due_event_provider=self._due_event_provider,
                )
                self._stages[key] = stage
            timer = self._expiry.pop(stage, None)
            if timer is not None:
                timer.cancel()
            try:
                await self._adapter.bind(stage, connection)
            except BaseException:
                self._schedule_expiry(stage)
                raise
            self._connections[stage] = connection
            lease = InteractionLease(key[0], key[1], stage.interaction_id, InteractionSource.CHAT)
            if not self._lease_registry.claim(lease):
                await self._adapter.disconnect(stage, connection)
                self._connections.pop(stage, None)
                raise ValueError("interaction is already owned")
            if key in self._pending_first_logins:
                self._pending_first_logins.remove(key)
                stage.schedule_first_login()
            if key in self._pending_regular_logins:
                self._pending_regular_logins.remove(key)
                stage.schedule_login_reminders()
            return stage

    def _require_chat_admission(self, key: tuple[str, str]) -> None:
        self._require_finalization_idle(key)
        current_lease = self._lease_registry.current(*key)
        if current_lease is not None and current_lease.source in {
            InteractionSource.CALL,
            InteractionSource.CALL_TRANSITION,
        }:
            raise InteractionOwnedByCallAdmission(current_lease.source)

    def _require_finalization_idle(self, key: tuple[str, str]) -> None:
        self._finalizations.require_idle(key)
        for call_id, ownership in self._call_ownerships.items():
            if (ownership.user_id, ownership.character_id) != key:
                continue
            stage = self._call_stages.get(call_id)
            if stage is not None and stage.state in {
                CallState.ENDING,
                CallState.ENDED,
                CallState.DECLINED,
            }:
                raise InteractionFinalizing()

    async def prepare_call_transition(
        self,
        connection: WebSocketConnection,
        *,
        character_id: str,
        client_request_id: str,
    ) -> CallTransitionIntent:
        """Prepare a one-shot transition only from the currently bound chat connection."""
        async with self._lock:
            if self._user_reset_fence is not None:
                await self._user_reset_fence.require_admission(connection.user_uuid)
            self._require_finalization_idle((connection.user_uuid, character_id))
            stage = self._bound_stage(connection, character_id)
            lease = InteractionLease(
                stage.user_id,
                stage.character_id,
                stage.interaction_id,
                InteractionSource.CHAT,
            )
            intent = self._lease_registry.prepare_call_transition(lease=lease, client_request_id=client_request_id)
            self._adapter.suspend_business_input(connection, interaction_id=stage.interaction_id)
            key = (stage.user_id, stage.character_id)
            old = self._intent_expiry.pop(key, None)
            if old is not None:
                old.cancel()
            self._intent_expiry[key] = asyncio.create_task(
                self._expire_call_intent(connection, stage, intent),
                name="call-intent-expiry",
            )
            return intent

    async def _claim_call(
        self,
        *,
        user_id: str,
        character_id: str,
        source_interaction_id: str | None,
        client_request_id: str,
    ) -> CallStartClaim:
        """Persist PREPARING, retire chat, close its context, then transfer ownership to CALL."""
        async with self._lock:
            if self._closed:
                raise RuntimeError("STAGE_MANAGER_CLOSED")
            self._require_finalization_idle((user_id, character_id))
            task = self._call_starts.get(client_request_id)
            operation_identity = (user_id, character_id, source_interaction_id)
            current_operation = self._call_start_operations.get(client_request_id)
            if current_operation is not None and current_operation != operation_identity:
                raise ValueError("client_request_id is already starting another call")
            if task is None:
                deadline = self._call_setup_deadlines.setdefault(
                    client_request_id,
                    self._monotonic() + self._config.call_setup_timeout,
                )
                if self._user_reset_fence is not None:
                    task, _ = await self._user_reset_fence.spawn_factory(
                        user_id,
                        lambda admitted: self._claim_call_operation(
                            user_id=user_id,
                            character_id=character_id,
                            source_interaction_id=source_interaction_id,
                            client_request_id=client_request_id,
                            setup_deadline=deadline,
                            admission_generation=admitted,
                        ),
                        name="call-handoff",
                    )
                else:
                    operation = self._claim_call_operation(
                        user_id=user_id,
                        character_id=character_id,
                        source_interaction_id=source_interaction_id,
                        client_request_id=client_request_id,
                        setup_deadline=deadline,
                        admission_generation=0,
                    )
                    task = asyncio.create_task(operation, name="call-handoff")
                self._call_starts[client_request_id] = task
                self._call_start_operations[client_request_id] = operation_identity
                task.add_done_callback(lambda finished, key=client_request_id: self._call_start_done(key, finished))
        return await complete_owned(self._await_call_start(task))

    async def _infer_call_source_interaction(self, *, user_id: str, character_id: str) -> str | None:
        """Return the only chat interaction a new call may transition from."""
        async with self._lock:
            stage = self._stages.get((user_id, character_id))
            return None if stage is None else stage.interaction_id

    @staticmethod
    async def _await_call_start(task: asyncio.Task[CallStartClaim]) -> CallStartClaim:
        return await asyncio.shield(task)

    def _call_start_done(self, client_request_id: str, task: asyncio.Task[CallStartClaim]) -> None:
        if self._call_starts.get(client_request_id) is task:
            self._call_starts.pop(client_request_id, None)
            self._call_start_operations.pop(client_request_id, None)
        if not task.cancelled() and task.exception() is not None:
            self._call_setup_deadlines.pop(client_request_id, None)
            get_logger(__name__).debug("Call handoff failed request=%s", client_request_id)

    async def _claim_call_operation(
        self,
        *,
        user_id: str,
        character_id: str,
        source_interaction_id: str | None,
        client_request_id: str,
        setup_deadline: float,
        admission_generation: int | None,
    ) -> CallStartClaim:
        if self._call_sessions is None:
            raise RuntimeError("call session repository is not bound")
        deadline = setup_deadline
        existing = await self._repository_call(self._call_sessions.find_by_request, client_request_id)
        self._require_setup_time(deadline)
        if existing is not None:
            return self._existing_call_claim(
                existing,
                user_id=user_id,
                character_id=character_id,
                setup_deadline=deadline,
            )
        generation = admission_generation or 0
        await self._require_generation(user_id, generation)
        record = await self._new_call_record(user_id, character_id, client_request_id)
        stage, connection, ownership = await self._begin_call_handoff(
            user_id=user_id,
            character_id=character_id,
            source_interaction_id=source_interaction_id,
            client_request_id=client_request_id,
        )
        try:
            record = await self._repository_call(self._call_sessions.create_if_absent, record)
        except BaseException:
            await self._rollback_preledger_handoff(stage, connection, ownership)
            raise
        if record.user_id != user_id or record.character_id != character_id:
            self._release_transition(ownership)
            raise ValueError("call request resolved to another owner")
        try:
            self._require_setup_time(deadline)
            if stage is not None:
                await self._commit_chat_handoff(stage, user_id=user_id, character_id=character_id)
                if connection is not None:
                    await self._adapter.disconnect(stage, connection)
                await self._terminate_for_call(stage, deadline)
            self._require_setup_time(deadline)
            async with self._lock:
                await self._require_generation(user_id, generation)
                if self._closed:
                    raise RuntimeError("stage manager closed during call handoff")
            call_lease = self._finish_transition(ownership, call_id=str(record.call_id))
            claim = CallStartClaim(record, call_lease, False, deadline, generation)
            self._call_claims[str(record.call_id)] = claim
            return claim
        except BaseException as error:
            await self._cleanup_postledger_failure(record, stage, ownership, error)
            raise

    async def _commit_chat_handoff(self, stage: ChatStage, *, user_id: str, character_id: str) -> None:
        async with self._lock:
            if self._user_reset_fence is not None:
                await self._user_reset_fence.require_admission(user_id)
            if self._closed:
                raise RuntimeError("stage manager closed during call handoff")
            self._stages.pop((user_id, character_id), None)
            timer = self._expiry.pop(stage, None)
            if timer is not None:
                timer.cancel()
            self._connections.pop(stage, None)

    async def _require_user_admission(self, user_id: str) -> None:
        async with self._lock:
            if self._user_reset_fence is not None:
                await self._user_reset_fence.require_admission(user_id)
            if self._closed:
                raise ValueError("stage manager is closed")

    async def _require_generation(self, user_id: str, generation: int) -> None:
        if self._user_reset_fence is not None:
            await self._user_reset_fence.require_generation(user_id, generation)

    async def _terminate_chat_for_call(self, stage):
        task = self._finalizations.start(
            stage.interaction_id,
            (stage.user_id, stage.character_id),
            lambda: stage.terminate(InteractionEndingReason.SWITCH_TO_CALL),
        )
        return await asyncio.shield(task)

    async def _terminate_for_call(self, stage: ChatStage, deadline: float) -> None:
        remaining = self._remaining_setup_time(deadline)
        termination = asyncio.create_task(self._terminate_chat_for_call(stage), name="chat-call-terminate")
        try:
            result = await asyncio.wait_for(asyncio.shield(termination), timeout=remaining)
        except asyncio.TimeoutError:
            await complete_owned(self._await_termination(termination))
            raise TimeoutError("call setup timed out") from None
        except asyncio.CancelledError:
            await complete_owned(self._await_termination(termination))
            raise
        if result.error is not None:
            raise RuntimeError(result.error)

    @staticmethod
    async def _await_termination(termination: asyncio.Task) -> None:
        await asyncio.shield(termination)

    def _finish_transition(
        self,
        ownership: CallTransitionOwnership | InteractionLease,
        *,
        call_id: str,
    ) -> InteractionLease:
        if isinstance(ownership, CallTransitionOwnership):
            return self._lease_registry.finish_call_transition(ownership, call_id=call_id)
        return self._lease_registry.finish_direct_call_transition(ownership, call_id=call_id)

    def _release_transition(self, ownership: CallTransitionOwnership | InteractionLease) -> None:
        if isinstance(ownership, CallTransitionOwnership):
            self._lease_registry.abandon_call_transition(ownership)
        else:
            self._lease_registry.release(ownership)

    async def _cleanup_postledger_failure(
        self,
        record: CallSessionRecord,
        stage: ChatStage | None,
        ownership: CallTransitionOwnership | InteractionLease,
        original_error: BaseException,
    ) -> None:
        if stage is not None and stage.state is not StageState.TERMINATED:
            await complete_owned(self._terminate_chat_for_call(stage))
        self._release_transition(ownership)
        try:
            await self._mark_call_failed(record, original_error)
        except Exception as cleanup_error:  # noqa: BLE001 - preserve original failure and report cleanup loss
            get_logger(__name__).error(
                "Failed to mark call ledger failed call=%s original_type=%s cleanup_type=%s",
                record.call_id,
                type(original_error).__name__,
                type(cleanup_error).__name__,
            )

    async def _repository_call(self, operation: Callable, *args, **kwargs):
        """Run one synchronous repository operation to completion outside the event loop."""
        return await complete_owned(self._to_thread(operation, *args, **kwargs))

    @staticmethod
    async def _to_thread(operation: Callable, *args, **kwargs):
        return await asyncio.to_thread(operation, *args, **kwargs)

    def _remaining_setup_time(self, deadline: float) -> float:
        remaining = deadline - self._monotonic()
        if remaining <= 0:
            raise TimeoutError("call setup timed out")
        return remaining

    def _require_setup_time(self, deadline: float) -> None:
        self._remaining_setup_time(deadline)

    def _existing_call_claim(
        self,
        record: CallSessionRecord,
        *,
        user_id: str,
        character_id: str,
        setup_deadline: float,
    ) -> CallStartClaim:
        if record.user_id != user_id or record.character_id != character_id:
            raise ValueError("client_request_id belongs to another call owner")
        if record.state in {
            CallState.FAILED,
            CallState.ENDING,
            CallState.ENDED,
            CallState.DECLINED,
        }:
            raise CallStartFailed(record)
        lease = self._lease_registry.current(user_id, character_id)
        if lease is None or lease.source is not InteractionSource.CALL or lease.interaction_id != str(record.call_id):
            raise ValueError("existing call is not owned by this runtime")
        pending = self._call_claims.get(str(record.call_id))
        generation = pending.admission_generation if pending is not None else 0
        return CallStartClaim(record, lease, True, setup_deadline, generation)

    def _take_call_claim(
        self,
        claim: CallStartClaim,
        *,
        user_id: str,
        character_id: str,
        client_request_id: str,
    ) -> CallStageOwnership:
        """Transfer one validated CALL claim to a future CallStage owner."""
        call_id = str(claim.record.call_id)
        if self._call_claims.get(call_id) != claim:
            raise ValueError("call claim is not pending or does not match")
        if (
            claim.record.user_id != user_id
            or claim.record.character_id != character_id
            or claim.record.client_request_id != client_request_id
            or claim.lease.user_id != user_id
            or claim.lease.character_id != character_id
            or claim.lease.interaction_id != call_id
            or claim.setup_deadline != self._call_setup_deadlines.get(client_request_id)
        ):
            raise ValueError("call claim identity mismatch")
        current = self._lease_registry.current(user_id, character_id)
        if current != claim.lease or current.source is not InteractionSource.CALL:
            raise ValueError("call lease is not current")
        self._call_ownership_generation += 1
        ownership = CallStageOwnership(
            call_id=call_id,
            user_id=user_id,
            character_id=character_id,
            client_request_id=client_request_id,
            setup_deadline=claim.setup_deadline,
            generation=self._call_ownership_generation,
        )
        self._call_claims.pop(call_id)
        self._call_ownerships[call_id] = ownership
        return ownership

    async def _fail_pending_call_claim(self, claim: CallStartClaim, error: BaseException) -> bool:
        """Fail only the still-pending claim identified by this exact value."""
        call_id = str(claim.record.call_id)
        async with self._lock:
            if self._call_claims.get(call_id) != claim:
                return False
            if call_id in self._call_ownerships or call_id in self._call_stages:
                return False
            current = self._lease_registry.current(claim.record.user_id, claim.record.character_id)
            if current != claim.lease or current.source is not InteractionSource.CALL:
                return False
            self._call_claims.pop(call_id)
            self._call_setup_deadlines.pop(claim.record.client_request_id, None)
            if not self._lease_registry.release(claim.lease):
                raise RuntimeError("pending call lease release failed")
        await self._mark_call_failed(claim.record, error)
        return True

    def _current_call_ownership(self, call_id: str) -> CallStageOwnership | None:
        return self._call_ownerships.get(call_id)

    async def _create_call_stage(
        self,
        claim: CallStartClaim,
        *,
        user_id: str,
        character_id: str,
        client_request_id: str,
        speech_factory: RealtimeSpeechSessionFactory,
        transport: CallTransportSink,
        call_metrics: CallMetrics | None = None,
        config: dict[str, object] | None = None,
        stage_created: Callable[[CallStage], None] | None = None,
        connection_available: bool = True,
    ) -> CallStage:
        """Consume a validated claim, then create and register exactly one CallStage."""
        await self._require_generation(user_id, claim.admission_generation)
        operation = self._create_call_stage_owned(
            claim,
            user_id=user_id,
            character_id=character_id,
            client_request_id=client_request_id,
            speech_factory=speech_factory,
            transport=transport,
            call_metrics=call_metrics,
            config=config,
            stage_created=stage_created,
            connection_available=connection_available,
        )
        if self._user_reset_fence is not None:
            task, _ = await self._user_reset_fence.spawn(user_id, operation, name="call-stage-create")
        else:
            task = asyncio.create_task(operation, name="call-stage-create")
        self._call_stage_creations.add(task)
        self._call_stage_creation_users[task] = user_id
        task.add_done_callback(self._call_stage_creation_done)
        return await asyncio.shield(task)

    async def _create_call_stage_owned(
        self,
        claim: CallStartClaim,
        *,
        user_id: str,
        character_id: str,
        client_request_id: str,
        speech_factory: RealtimeSpeechSessionFactory,
        transport: CallTransportSink,
        call_metrics: Any | None,
        config: dict[str, object] | None,
        stage_created: Callable[[CallStage], None] | None,
        connection_available: bool,
    ) -> CallStage:
        from .call_stage import CallStage

        await self._require_generation(user_id, claim.admission_generation)
        ownership = self._take_call_claim(
            claim,
            user_id=user_id,
            character_id=character_id,
            client_request_id=client_request_id,
        )
        if self._call_sessions is None:
            self._release_call(ownership)
            raise RuntimeError("call session repository is not bound")
        stage = None
        try:
            stage = CallStage(
                ownership=ownership,
                record=claim.record,
                agent=self._get_agent(character_id),
                context_factory=self._get_context_factory(character_id),
                call_sessions=self._call_sessions,
                speech_factory=speech_factory,
                transport=transport,
                release_ownership=self._release_call_stage_ownership,
                settlement_sink=CallFinalizationSink(self, ownership),
                termination_owner=lambda current, reason: self._start_call_termination(current, ownership, reason),
                call_metrics=call_metrics,
                monotonic=self._monotonic,
                wall_clock=self._wall_clock,
                config=config,
                connection_available=connection_available,
            )
            bind_stage = getattr(transport, "bind_stage", None)
            if bind_stage is not None:
                bind_stage(stage)
            if stage_created is not None:
                stage_created(stage)
            await stage.start()
        except BaseException as original_error:
            if stage is not None and stage.termination_requested:
                await stage.terminate()
                return stage
            await self._cleanup_failed_call_stage(
                claim=claim,
                ownership=ownership,
                stage=stage,
                transport=transport,
                original_error=original_error,
            )
            raise
        await self._require_generation(user_id, claim.admission_generation)
        async with self._lock:
            should_close = self._closed
            if (
                not should_close
                and stage.snapshot is None
                and self._current_call_ownership(ownership.call_id) == ownership
            ):
                self._call_stages[ownership.call_id] = stage
        if should_close:
            await stage.close()
            raise ValueError("stage manager closed during call stage creation")
        return stage

    async def _cleanup_failed_call_stage(self, *, claim, ownership, stage, transport, original_error) -> None:
        if stage is not None and stage.snapshot is None:
            try:
                await stage.abort_failed_start()
            except BaseException as cleanup_error:
                self._log_call_cleanup_failure("stage", claim, original_error, cleanup_error)
        reason = (
            CallEndReason.SETUP_TIMEOUT
            if isinstance(original_error, (TimeoutError, asyncio.TimeoutError))
            or self._monotonic() >= claim.setup_deadline
            else CallEndReason.SYSTEM_FAILURE
        )
        send_failed = getattr(transport, "send_failed", None)
        if send_failed is not None:
            try:
                await send_failed(reason)
            except BaseException as cleanup_error:
                self._log_call_cleanup_failure("failure delivery", claim, original_error, cleanup_error)
        self._release_call(ownership)
        try:
            await self._mark_call_failed(claim.record, original_error)
        except BaseException as cleanup_error:
            self._log_call_cleanup_failure("ledger", claim, original_error, cleanup_error)

    @staticmethod
    def _log_call_cleanup_failure(kind, claim, original_error, cleanup_error) -> None:
        get_logger(__name__).error(
            "Call postclaim %s cleanup failed call=%s original_type=%s cleanup_type=%s",
            kind,
            claim.record.call_id,
            type(original_error).__name__,
            type(cleanup_error).__name__,
        )

    def _call_stage_creation_done(self, task: asyncio.Task[Any]) -> None:
        self._call_stage_creations.discard(task)
        self._call_stage_creation_users.pop(task, None)

    def _release_call_stage_ownership(self, ownership: CallStageOwnership) -> bool:
        self._call_stages.pop(ownership.call_id, None)
        return self._release_call(ownership)

    def _release_call(self, ownership: CallStageOwnership) -> bool:
        """Release only the current CallStage ownership generation."""
        if self._call_ownerships.get(ownership.call_id) != ownership:
            return False
        lease = self._lease_registry.current(ownership.user_id, ownership.character_id)
        if lease is None or lease.source is not InteractionSource.CALL or lease.interaction_id != ownership.call_id:
            return False
        if not self._lease_registry.release(lease):
            return False
        self._call_ownerships.pop(ownership.call_id)
        self._call_setup_deadlines.pop(ownership.client_request_id, None)
        return True

    async def _begin_call_handoff(
        self,
        *,
        user_id: str,
        character_id: str,
        source_interaction_id: str | None,
        client_request_id: str,
    ) -> tuple[
        ChatStage | None,
        WebSocketConnection | None,
        CallTransitionOwnership | InteractionLease,
    ]:
        async with self._lock:
            if self._closed:
                raise ValueError("stage manager is closed")
            if source_interaction_id is None:
                direct = self._lease_registry.begin_direct_call_transition(
                    user_id=user_id,
                    character_id=character_id,
                    client_request_id=client_request_id,
                )
                if direct is None:
                    raise ValueError("interaction is already owned")
                return None, None, direct
            stage = self._stages.get((user_id, character_id))
            if stage is None or stage.interaction_id != source_interaction_id:
                raise ValueError("source chat interaction is not reusable")
            ownership = self._lease_registry.begin_call_transition(
                user_id=user_id,
                character_id=character_id,
                source_interaction_id=source_interaction_id,
                client_request_id=client_request_id,
            )
            if ownership is None:
                raise ValueError("matching call transition intent is required")
            expiry = self._intent_expiry.pop((user_id, character_id), None)
            if expiry is not None:
                expiry.cancel()
            return stage, self._connections.get(stage), ownership

    async def _rollback_preledger_handoff(
        self,
        stage: ChatStage | None,
        connection: WebSocketConnection | None,
        ownership: CallTransitionOwnership | InteractionLease,
    ) -> None:
        if isinstance(ownership, CallTransitionOwnership):
            async with self._lock:
                reusable = (
                    stage is not None
                    and self._stages.get((stage.user_id, stage.character_id)) is stage
                    and stage.state not in (StageState.TERMINATING, StageState.TERMINATED)
                )
                if reusable:
                    self._lease_registry.rollback_call_transition(ownership)
                    if (
                        self._connections.get(stage) is connection
                        and connection is not None
                        and not connection.is_closed
                    ):
                        self._adapter.resume_business_input(connection, interaction_id=stage.interaction_id)
                    return
            self._lease_registry.abandon_call_transition(ownership)
        else:
            self._lease_registry.release(ownership)

    async def _expire_call_intent(
        self,
        connection: WebSocketConnection,
        stage: ChatStage,
        intent: CallTransitionIntent,
    ) -> None:
        await asyncio.sleep(max(0.0, intent.expires_at - time.monotonic()))
        async with self._lock:
            key = (stage.user_id, stage.character_id)
            if self._intent_expiry.get(key) is not asyncio.current_task():
                return
            self._intent_expiry.pop(key, None)
            current = self._lease_registry.current(*key)
            if current is not None and current.source is InteractionSource.CHAT:
                self._adapter.resume_business_input(connection, interaction_id=stage.interaction_id)

    async def _new_call_record(self, user_id: str, character_id: str, client_request_id: str) -> CallSessionRecord:
        now = await self._next_call_timestamp()
        return CallSessionRecord(
            call_id=uuid4(),
            client_request_id=client_request_id,
            user_id=user_id,
            character_id=character_id,
            state=CallState.PREPARING,
            requested_at=now,
            created_at=now,
            updated_at=now,
        )

    async def _next_call_timestamp(self) -> datetime:
        async with self._time_lock:
            raw = self._wall_clock()
            if raw.tzinfo is None or raw.utcoffset() is None:
                raise ValueError("call wall clock must be timezone-aware")
            candidate = raw.astimezone(BEIJING_TIMEZONE)
            if self._last_call_timestamp is not None and candidate <= self._last_call_timestamp:
                candidate = self._last_call_timestamp + timedelta(microseconds=1)
            self._last_call_timestamp = candidate
            return candidate

    async def _mark_call_failed(self, record: CallSessionRecord, error: BaseException) -> None:
        end_reason = (
            CallEndReason.SETUP_TIMEOUT
            if isinstance(error, (TimeoutError, asyncio.TimeoutError))
            else CallEndReason.SYSTEM_FAILURE
        )
        current = await self._repository_call(self._call_sessions.find_by_id, record.call_id)
        if current is None or current.state is CallState.FAILED:
            return
        failed = current.with_update(
            state=CallState.FAILED,
            end_reason=end_reason,
            updated_at=await self._next_call_timestamp(),
        )
        await self._repository_call(
            self._call_sessions.update_if_state,
            record.call_id,
            expected_state=current.state,
            record=failed,
        )

    def _bound_stage(self, connection: WebSocketConnection, character_id: str) -> ChatStage:
        matches = [
            stage
            for stage, current in self._connections.items()
            if current is connection and stage.character_id == character_id
        ]
        if len(matches) != 1:
            raise ValueError("current chat connection is not bound to the character")
        return matches[0]

    async def _disconnect(self, connection: WebSocketConnection) -> None:
        async with self._lock:
            connection.mark_disconnected()
            for stage, current in list(self._connections.items()):
                if current is connection:
                    await self._adapter.disconnect(stage, connection)
                    self._connections.pop(stage, None)
                    self._schedule_expiry(stage)

    async def _close(self) -> None:
        async with self._lock:
            self._closed = True
            self._recovery_ready = False
            initialization = self._initialization
            stages = tuple(self._stages.values())
            self._stages.clear()
            timers = tuple(self._expiry.values())
            self._expiry.clear()
            for timer in timers:
                timer.cancel()
            intent_timers = tuple(self._intent_expiry.values())
            self._intent_expiry.clear()
        if initialization is not None and initialization is not asyncio.current_task():
            await asyncio.gather(initialization, return_exceptions=True)
        await asyncio.gather(*timers, return_exceptions=True)
        for timer in intent_timers:
            timer.cancel()
        await asyncio.gather(*intent_timers, return_exceptions=True)
        current = asyncio.current_task()
        starts = tuple(task for task in self._call_starts.values() if task is not current)
        if starts:
            await asyncio.gather(*starts, return_exceptions=True)
        creations = tuple(task for task in self._call_stage_creations if task is not current)
        for creation in creations:
            creation.cancel()
        if creations:
            await asyncio.gather(*creations, return_exceptions=True)
        for stage in stages:
            await asyncio.shield(self._start_chat_finalization(stage, InteractionEndingReason.SHUTDOWN))
        call_stages = tuple(self._call_stages.values())
        if call_stages:
            await asyncio.gather(*(stage.close() for stage in call_stages), return_exceptions=True)
        controls = tuple(control for control in self._call_controls.values() if control._stage not in call_stages)
        if controls:
            await asyncio.gather(
                *(control.terminate(CallEndReason.SYSTEM_FAILURE) for control in controls),
                return_exceptions=True,
            )
        self._call_stages.clear()
        await self._finalizations.close()
        self._lease_registry.close()
        self._call_setup_deadlines.clear()
        self._call_claims.clear()
        self._call_ownerships.clear()

    def _schedule_expiry(self, stage: ChatStage) -> None:
        old = self._expiry.pop(stage, None)
        if old is not None:
            old.cancel()
        self._expiry[stage] = asyncio.create_task(self._expire(stage), name="stage-offline-expiry")

    async def _expire(self, stage: ChatStage) -> None:
        await asyncio.sleep(self._config.offline_timeout)
        async with self._lock:
            if self._expiry.get(stage) is not asyncio.current_task():
                return
            self._expiry.pop(stage, None)
            key = (stage.user_id, stage.character_id)
            if self._stages.get(key) is stage:
                del self._stages[key]
            self._start_chat_finalization(stage, InteractionEndingReason.USER_LEFT)

    def _start_chat_finalization(self, stage, reason):
        return self._finalizations.start(
            stage.interaction_id,
            (stage.user_id, stage.character_id),
            lambda: self._retire(stage, reason),
        )

    async def _retire(self, stage: ChatStage, reason: InteractionEndingReason) -> None:
        try:
            result = await stage.terminate(reason)
            if result.error is not None:
                get_logger(__name__).error(
                    "Stage retirement failed interaction=%s error=%s",
                    stage.interaction_id,
                    result.error,
                )
        except Exception as error:
            get_logger(__name__).error(
                "Stage retirement raised interaction=%s type=%s",
                stage.interaction_id,
                type(error).__name__,
            )
        finally:
            await self._adapter.disconnect(stage)
            self._connections.pop(stage, None)
            self._lease_registry.release(
                InteractionLease(
                    stage.user_id,
                    stage.character_id,
                    stage.interaction_id,
                    InteractionSource.CHAT,
                )
            )
