"""管理聊天、通话的接入、占用及收尾任务。"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime
from functools import partial
from typing import TYPE_CHECKING, Any, TypeVar

from src.agent.context import ContextFactory
from src.domain.stage import StageState
from src.domain.stage.due_events import DueEventProvider
from src.domain.stage.lifecycle import (
    ConnectedStage,
    ManagedStage,
    StageEndReason,
    StageHandoffFailed,
    StageLifecycleState,
    StageShutdownFailed,
    StageStartAborted,
    StageTerminationResult,
)
from src.domain.stage.transport import StageOutputSink
from src.utils.logger import get_logger
from src.utils.owned_operation import complete_owned

from ._finalization import FinalizationTasks, InteractionFinalizing
from .call._call_records import CallRecords, PreparedCall
from .call.call_stage import CallStage, CallStageOutput, CallStageOwnership, bind_call_stage_creator
from .chat.chat_stage import ChatStage
from .interaction_lease import (
    CallTransitionIntent,
    CallTransitionOwnership,
    InteractionLease,
    InteractionLeaseRegistry,
    InteractionSource,
)

if TYPE_CHECKING:
    from src.agent.facade import Agent
    from src.domain.stage.connection import InteractionConnection
    from src.infrastructure.models.realtime_speech import RealtimeSpeechSessionFactory
    from src.infrastructure.observability.call_metrics import CallMetrics
    from src.infrastructure.persistence.call_maintenance import (
        SqlCallMaintenanceBatchRepository,
    )
    from src.infrastructure.persistence.call_sessions import CallSessionRepository
    from src.infrastructure.persistence.database.services.conversation_service import (
        ConversationService,
    )


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
class _CallStartClaim:
    """Manager 内部尚未交付 Stage 的交互占用。"""

    prepared: PreparedCall
    lease: InteractionLease
    duplicate: bool
    setup_deadline: float
    admission_generation: int = 0


@dataclass(frozen=True, slots=True)
class _CallOpenRequest:
    """Manager 内部建立操作身份，不作为 Adapter 请求契约。"""

    user_id: str
    character_id: str
    client_request_id: str
    source_interaction_id: str | None = None


@dataclass
class _Handoff:
    source: ChatStage | None
    connection: object
    ownership: CallTransitionOwnership | InteractionLease
    committed: bool = False


_Stage = TypeVar("_Stage", bound=ManagedStage)


@dataclass(frozen=True)
class _StageRegistration:
    """公共生命周期及接入时确定的管理元数据；用户归属不侵入 Stage 公共协议。"""

    stage: ManagedStage
    user_id: str
    release: Callable[[], Awaitable[None]]

    @property
    def scope(self) -> tuple[str, str]:
        return self.user_id, self.stage.character_id


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
        chat_output_sink: StageOutputSink,
        detach_stage_binding: Callable[[ChatStage, InteractionConnection | None], Awaitable[None]],
        get_context_factory: Callable[[str], ContextFactory],
        call_output_sink: Callable[[str, CallStageOutput], Awaitable[None]] | None = None,
        due_event_provider: DueEventProvider | None = None,
        lease_registry: InteractionLeaseRegistry | None = None,
        call_sessions: CallSessionRepository | None = None,
        conversation_service: ConversationService | None = None,
        call_maintenance_batches: SqlCallMaintenanceBatchRepository | None = None,
        call_metrics: CallMetrics | None = None,
        realtime_speech_factory: RealtimeSpeechSessionFactory | None = None,
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
        self._call_stage_config = config.get("call_stage", {})
        if not isinstance(self._call_stage_config, dict):
            raise TypeError("call_stage config must be a dictionary")
        self._get_agent = get_agent
        self._chat_output_sink = chat_output_sink
        self._detach_stage_binding = detach_stage_binding
        self._get_context_factory = get_context_factory
        self._due_event_provider = due_event_provider
        self._lease_registry = lease_registry or InteractionLeaseRegistry()
        self._call_records = CallRecords(call_sessions=call_sessions, wall_clock=wall_clock)
        self._call_stage_creator = bind_call_stage_creator(
            get_agent=get_agent,
            get_context_factory=get_context_factory,
            call_sessions=call_sessions,
            conversation_service=conversation_service,
            call_maintenance_batches=call_maintenance_batches,
            call_metrics=call_metrics,
            speech_factory=realtime_speech_factory,
            output_sink=call_output_sink,
            monotonic=monotonic,
            wall_clock=wall_clock,
        )
        self._user_reset_fence = user_reset_fence
        self._monotonic = monotonic
        self._stages: dict[tuple[str, str], ChatStage] = {}
        self._chat_creations: dict[tuple[str, str], asyncio.Task[ChatStage]] = {}
        self._connections: dict[ChatStage, InteractionConnection] = {}
        self._expiry: dict[ConnectedStage, asyncio.Task[None]] = {}
        self._finalizations = FinalizationTasks()
        self._managed: dict[str, _StageRegistration] = {}
        self._initializations: set[asyncio.Task[None]] = set()
        self._terminations: dict[str, asyncio.Task[StageTerminationResult]] = {}
        self._termination_results: dict[str, StageTerminationResult] = {}
        self._handoffs = {}
        self._scope_releases = set()
        self._lock = asyncio.Lock()
        self._closed = False
        self._closing: asyncio.Task[None] | None = None
        self._pending_first_logins: set[tuple[str, str]] = set()
        self._pending_regular_logins: set[tuple[str, str]] = set()
        self._call_starts: dict[str, asyncio.Task[_CallStartClaim]] = {}
        self._call_start_operations: dict[str, tuple[str, str, str | None]] = {}
        self._call_setup_deadlines: dict[str, float] = {}
        self._call_claims: dict[str, _CallStartClaim] = {}
        self._call_ownerships: dict[str, CallStageOwnership] = {}
        self._call_stages: dict[str, CallStage] = {}
        self._call_stages_by_request: dict[str, CallStage] = {}
        self._call_open_tasks: dict[str, asyncio.Task[CallStage]] = {}
        self._call_stage_creations: dict[asyncio.Task[Any], str] = {}
        self._call_ownership_generation = 0
        self._intent_expiry: dict[tuple[str, str], asyncio.Task[None]] = {}

    @property
    def call_business_ready(self) -> bool:
        """返回通话依赖的完整就绪事实。"""
        return not self._closed and self._call_stage_creator is not None

    async def initialize(self) -> None:
        """Validate admission without replaying calls from an earlier process."""
        if self._closed:
            raise RuntimeError("stage manager closed during initialization")

    async def _get_call_stage(self, request: _CallOpenRequest) -> CallStage:
        """接管呼叫并返回 PREPARING Stage，不等待 Context 或供应商初始化。"""
        if not self.call_business_ready:
            raise RuntimeError("CALL_INGRESS_UNAVAILABLE")
        request = replace(
            request,
            source_interaction_id=request.source_interaction_id
            or await self._infer_call_source_interaction(user_id=request.user_id, character_id=request.character_id),
        )
        existing = await self._find_call_by_request(
            request.client_request_id, user_id=request.user_id, character_id=request.character_id
        )
        if existing is not None:
            return existing
        task = asyncio.create_task(self._open_call(request), name=f"call-open-{request.client_request_id}")
        self._call_open_tasks[request.client_request_id] = task
        task.add_done_callback(lambda done: self._observe_open_call(request.client_request_id, done))
        return await asyncio.shield(task)

    async def _open_call(self, request: _CallOpenRequest) -> CallStage:
        claim = await self._claim_call(
            user_id=request.user_id,
            character_id=request.character_id,
            source_interaction_id=request.source_interaction_id,
            client_request_id=request.client_request_id,
        )
        stage = await self._create_call_stage(
            claim,
            user_id=request.user_id,
            character_id=request.character_id,
            client_request_id=request.client_request_id,
            initialize=False,
            connection_available=False,
            config=self._call_stage_config,
        )
        if stage.interaction_id in self._managed:
            self._call_stages_by_request[request.client_request_id] = stage
        return stage

    def _observe_open_call(self, request_id: str, task: asyncio.Task) -> None:
        if self._call_open_tasks.get(request_id) is task:
            self._call_open_tasks.pop(request_id, None)
        if not task.cancelled() and task.exception() is not None:
            get_logger(__name__).error(
                "Call open failed request=%s type=%s", request_id, type(task.exception()).__name__
            )

    async def _resume_call_stage(self, call_id: str, *, user_id: str, character_id: str) -> CallStage:
        stage = self._call_stages.get(call_id)
        if stage is None:
            raise RuntimeError("CALL_NOT_FOUND")
        if stage.user_id != user_id or stage.character_id != character_id:
            raise RuntimeError("RESUME_OWNERSHIP_MISMATCH")
        # ACTIVE 可以等待旧连接释放；真正恢复时由 Stage 再检查状态和期限。
        if not stage.can_attach():
            raise RuntimeError("CALL_RESUME_UNAVAILABLE")
        return stage

    async def _find_call_by_request(
        self, client_request_id: str, *, user_id: str, character_id: str
    ) -> CallStage | None:
        task = self._call_open_tasks.get(client_request_id)
        stage = await asyncio.shield(task) if task is not None else self._call_stages_by_request.get(client_request_id)
        if stage is not None:
            if stage.user_id != user_id or stage.character_id != character_id:
                raise ValueError("client_request_id belongs to another call owner")
            if stage.interaction_ended:
                raise RuntimeError("CALL_RESUME_UNAVAILABLE")
            return stage
        prepared = await self._call_records.find_start(client_request_id, user_id=user_id, character_id=character_id)
        # 查询账本期间另一接入可能已经建立任务，始终复用其唯一 Stage。
        task = self._call_open_tasks.get(client_request_id)
        stage = await asyncio.shield(task) if task is not None else self._call_stages_by_request.get(client_request_id)
        if stage is not None:
            if stage.user_id != user_id or stage.character_id != character_id:
                raise ValueError("client_request_id belongs to another call owner")
            if stage.interaction_ended:
                raise RuntimeError("CALL_RESUME_UNAVAILABLE")
            return stage
        if prepared is not None:
            prepared.reject()
        return None

    def _own_initialization(
        self,
        stage: _Stage,
        operation: Callable[[], Awaitable[None]],
        *,
        user_id: str,
        release: Callable[[_Stage], Awaitable[None]],
    ) -> asyncio.Task[None]:
        registration = _StageRegistration(stage, user_id, partial(release, stage))
        self._managed[stage.interaction_id] = registration
        task = asyncio.create_task(
            self._initialize_stage(registration, operation), name=f"stage-initialize-{stage.interaction_id}"
        )
        self._initializations.add(task)
        task.add_done_callback(self._initializations.discard)
        return task

    async def _initialize_stage(
        self, registration: _StageRegistration, operation: Callable[[], Awaitable[None]]
    ) -> None:
        stage = registration.stage
        generation = 0
        if self._user_reset_fence is not None:
            generation = await self._user_reset_fence.track_current(registration.user_id)
        try:
            await operation()
            await self._require_generation(registration.user_id, generation)
        except StageStartAborted:
            raise
        except Exception:
            get_logger(__name__).exception("Stage initialization failed interaction=%s", stage.interaction_id)
            stage.begin_termination(StageEndReason.INITIALIZATION_FAILED)
            raise

    def _own_termination(
        self, stage: ManagedStage, operation: Callable[[], Awaitable[StageTerminationResult]]
    ) -> asyncio.Task[StageTerminationResult]:
        registration = self._managed[stage.interaction_id]
        task = self._finalizations.start(
            stage.interaction_id,
            registration.scope,
            lambda: self._finish_stage(registration, operation),
        )
        self._terminations[stage.interaction_id] = task
        return task

    async def _finish_stage(
        self, registration: _StageRegistration, operation: Callable[[], Awaitable[StageTerminationResult]]
    ) -> StageTerminationResult:
        stage = registration.stage
        result = await operation()
        self._termination_results[stage.interaction_id] = result
        if result.finalization_error or result.cleanup_error:
            get_logger(__name__).error(
                "Stage finalization failed interaction=%s result=%s", stage.interaction_id, result
            )
        if not result.resources_released:
            return result
        await registration.release()
        return result

    def _forget_stage(self, stage: ManagedStage) -> None:
        self._managed.pop(stage.interaction_id, None)
        self._termination_results.pop(stage.interaction_id, None)
        self._terminations.pop(stage.interaction_id, None)

    async def _release_chat_stage(self, stage: ChatStage) -> None:
        await self._detach_stage_binding(stage, None)
        self._connections.pop(stage, None)
        key = (stage.user_id, stage.character_id)
        if self._stages.get(key) is stage:
            self._stages.pop(key)
        self._lease_registry.release(InteractionLease(*key, stage.interaction_id, InteractionSource.CHAT))
        self._forget_stage(stage)

    async def _release_call_stage(self, stage: CallStage) -> None:
        handoff = self._handoffs.get(stage.call_id)
        if handoff and handoff.committed and handoff.source is not None:
            task = asyncio.create_task(self._release_call_scope(stage), name="stage-handoff-release")
            self._scope_releases.add(task)
            task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        else:
            await self._release_call_scope(stage)

    async def _release_call_scope(self, stage: CallStage) -> None:
        await self._finish_call_ownership(stage)
        self._forget_stage(stage)
        self._scope_releases.discard(asyncio.current_task())

    async def _finish_call_ownership(self, stage):
        handoff = self._handoffs.get(stage.call_id)
        if handoff is not None:
            source = handoff.source
            if handoff.committed:
                if source is not None:
                    result = await source.terminate(StageEndReason.SWITCH)
                    if not result.resources_released:
                        raise StageShutdownFailed("source stage resources remain owned")
                self._release_transition(handoff.ownership)
            elif source is not None:
                self._handoffs.pop(stage.call_id, None)
                await self._restore_chat_after_handoff(source, handoff.ownership, refresh_history=True)
            else:
                self._release_transition(handoff.ownership)
            self._handoffs.pop(stage.call_id, None)
        ownership = self._call_ownerships.get(stage.call_id)
        if ownership is not None:
            self._release_call_stage_ownership(ownership)
            self._call_ownerships.pop(stage.call_id, None)
            self._call_setup_deadlines.pop(stage.client_request_id, None)

    async def _finish_source_interaction(self, call):
        async with self._lock:
            if self._closed or call.termination_requested:
                raise StageHandoffFailed("call ended before handoff commit")
            handoff = self._handoffs[call.call_id]
            handoff.committed = True
            source = handoff.source
            if source is not None:
                self._stages.pop((source.user_id, source.character_id), None)
                self._connections.pop(source, None)
                source.begin_termination(StageEndReason.SWITCH)
        if source is not None:
            result = await source.terminate(StageEndReason.SWITCH)
            if result.finalization_error or result.cleanup_error or not result.resources_released:
                raise StageHandoffFailed("source stage did not finalize successfully")
        if call.termination_requested:
            raise StageHandoffFailed("call ended during source finalization")
        self._finish_transition(handoff.ownership, call_id=call.call_id)

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
            any(entry.user_id == user_id for entry in self._managed.values())
            or self._finalizations.has_user(user_id)
            or any(owner == user_id for owner, _ in self._stages)
            or any(owner == user_id for owner, _ in self._chat_creations)
            or any(owner.user_id == user_id for owner in self._call_ownerships.values())
            or any(claim.prepared.user_id == user_id for claim in self._call_claims.values())
            or any(owner[0] == user_id for owner in self._call_start_operations.values())
            or any(owner == user_id and not task.done() for task, owner in self._call_stage_creations.items())
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
                if owner_id == user_id
                and stage.lifecycle_state not in (StageLifecycleState.TERMINATING, StageLifecycleState.TERMINATED)
            )
            for stage in stages:
                await stage.propose_relationship(relationship)
            return len(stages)

    async def try_to_get_stage(
        self,
        *,
        user_id: str,
        character_id: str,
        stage_type: str = "chat",
        connection: InteractionConnection | None = None,
        call_id: str | None = None,
        client_request_id: str | None = None,
        source_interaction_id: str | None = None,
    ) -> ChatStage | CallStage:
        """按交互规则复用、恢复或创建；拒绝通过具名异常表达。"""
        if stage_type == "call":
            if call_id is not None:
                return await self._resume_call_stage(call_id, user_id=user_id, character_id=character_id)
            if not client_request_id:
                raise ValueError("call start requires request identity")
            return await self._get_call_stage(
                _CallOpenRequest(user_id, character_id, client_request_id, source_interaction_id)
            )
        if stage_type != "chat" or connection is None or connection.user_uuid != user_id:
            raise ValueError("chat admission requires its authenticated connection")
        return await complete_owned(self._connect(connection, character_id))

    async def disconnect(self, connection: InteractionConnection) -> None:
        """接收 Adapter 已解绑的断线通知并启动离线保留期；旧连接通知不影响重连。"""
        await complete_owned(self._disconnect(connection))

    async def close(self) -> None:
        """停止接入，终止全部 Stage 并解除绑定，等待正在执行的离线回收任务。"""
        if self._closing is None:
            self._closing = asyncio.create_task(self._close(), name="stage-manager-close")
        await asyncio.shield(self._closing)

    def is_closed(self) -> bool:
        return self._closed

    async def _connect(self, connection: InteractionConnection, character_id: str) -> ChatStage:
        key = (connection.user_uuid, character_id)
        async with self._lock:
            if self._user_reset_fence is not None:
                await self._user_reset_fence.track_current(connection.user_uuid)
            self._require_chat_connection(connection, key)
            stage = self._stages.get(key)
            if stage is None or stage.lifecycle_state in (
                StageLifecycleState.TERMINATING,
                StageLifecycleState.TERMINATED,
            ):
                creation = self._chat_creations.get(key)
                if creation is None:
                    creation = asyncio.create_task(self._create_chat_stage(key), name="chat-stage-create")
                    self._chat_creations[key] = creation
                    creation.add_done_callback(lambda done: self._chat_creation_done(key, done))
            else:
                creation = None
        if creation is not None:
            stage = await asyncio.shield(creation)
        return await self._claim_chat_connection(stage, connection, key)

    async def _claim_chat_connection(self, stage, connection, key) -> ChatStage:
        async with self._lock:
            try:
                self._require_chat_connection(connection, key)
            except BaseException:
                if self._stages.get(key) is stage and stage not in self._connections:
                    self._schedule_expiry(stage)
                raise
            if self._stages.get(key) is not stage:
                raise ValueError("chat stage is no longer current")
            timer = self._expiry.pop(stage, None)
            if timer is not None:
                timer.cancel()
            self._connections[stage] = connection
            lease = InteractionLease(key[0], key[1], stage.interaction_id, InteractionSource.CHAT)
            if not self._lease_registry.claim(lease):
                await self._detach_stage_binding(stage, connection)
                self._connections.pop(stage, None)
                raise ValueError("interaction is already owned")
            if key in self._pending_first_logins:
                self._pending_first_logins.remove(key)
                stage.schedule_first_login()
            if key in self._pending_regular_logins:
                self._pending_regular_logins.remove(key)
                stage.schedule_login_reminders()
            return stage

    def _require_chat_connection(self, connection, key) -> None:
        if self._closed or connection.is_closed or not connection.user_uuid:
            raise ValueError("manager or connection is unavailable")
        self._require_chat_admission(key)

    async def _create_chat_stage(self, key: tuple[str, str]) -> ChatStage:
        generation = 0
        if self._user_reset_fence is not None:
            generation = await self._user_reset_fence.track_current(key[0])
        stage = await ChatStage.create(
            user_id=key[0],
            character_id=key[1],
            agent=self._get_agent(key[1]),
            output_sink=self._chat_output_sink,
            config=self._stage_config,
            context_factory=self._get_context_factory(key[1]),
            due_event_provider=self._due_event_provider,
            own_initialization=partial(self._own_initialization, user_id=key[0], release=self._release_chat_stage),
            own_termination=self._own_termination,
            retention_changed=self._update_retention,
            offline_timeout=self._config.offline_timeout,
            monotonic=self._monotonic,
        )
        try:
            async with self._lock:
                await self._require_generation(key[0], generation)
                if self._closed:
                    raise ValueError("stage manager closed during chat creation")
                self._require_chat_admission(key)
                lease = InteractionLease(*key, stage.interaction_id, InteractionSource.CHAT)
                previous = self._stages.get(key)
                if previous is not None and previous.lifecycle_state is StageLifecycleState.TERMINATED:
                    self._lease_registry.release(
                        InteractionLease(*key, previous.interaction_id, InteractionSource.CHAT)
                    )
                if not self._lease_registry.claim(lease):
                    raise ValueError("interaction is already owned")
                self._stages[key] = stage
            return stage
        except BaseException:
            await asyncio.shield(self._start_chat_finalization(stage, StageEndReason.SHUTDOWN))
            raise

    def _chat_creation_done(self, key, task) -> None:
        if self._chat_creations.get(key) is task:
            self._chat_creations.pop(key, None)
        if not task.cancelled():
            task.exception()

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
        if any(
            entry.scope == key and entry.stage.lifecycle_state is StageLifecycleState.TERMINATING
            for entry in self._managed.values()
        ):
            raise InteractionFinalizing()
        for call_id, ownership in self._call_ownerships.items():
            if (ownership.user_id, ownership.character_id) != key:
                continue
            stage = self._call_stages.get(call_id)
            if stage is not None and stage.lifecycle_state in (
                StageLifecycleState.TERMINATING,
                StageLifecycleState.TERMINATED,
            ):
                raise InteractionFinalizing()

    async def prepare_call_transition(
        self,
        connection: InteractionConnection,
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
            stage.set_input_suspended(True)
            key = (stage.user_id, stage.character_id)
            old = self._intent_expiry.pop(key, None)
            if old is not None:
                old.cancel()
            self._intent_expiry[key] = asyncio.create_task(
                self._expire_call_intent(stage, intent),
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
    ) -> _CallStartClaim:
        """登记 PREPARING 和临时占用，耗时切换由 Stage 初始化后段发起。"""
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
    async def _await_call_start(task: asyncio.Task[_CallStartClaim]) -> _CallStartClaim:
        return await asyncio.shield(task)

    def _call_start_done(self, client_request_id: str, task: asyncio.Task[_CallStartClaim]) -> None:
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
    ) -> _CallStartClaim:
        deadline = setup_deadline
        existing = await self._call_records.find_start(client_request_id, user_id=user_id, character_id=character_id)
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
        stage, connection, ownership = await self._begin_call_handoff(
            user_id=user_id,
            character_id=character_id,
            source_interaction_id=source_interaction_id,
            client_request_id=client_request_id,
        )
        try:
            prepared = await self._call_records.prepare_start(
                user_id=user_id, character_id=character_id, client_request_id=client_request_id
            )
        except BaseException:
            await self._restore_chat_after_handoff(stage, ownership)
            raise
        try:
            self._require_setup_time(deadline)
            await self._require_generation(user_id, generation)
            if self._closed:
                raise RuntimeError("stage manager closed during call creation")
            self._handoffs[prepared.call_id] = _Handoff(stage, connection, ownership)
            lease = ownership.lease if isinstance(ownership, CallTransitionOwnership) else ownership
            claim = _CallStartClaim(prepared, lease, False, deadline, generation)
            self._call_claims[prepared.call_id] = claim
            return claim
        except BaseException as error:
            await self._call_records.abort_start(prepared, error)
            await self._restore_chat_after_handoff(stage, ownership)
            raise

    async def _require_user_admission(self, user_id: str) -> None:
        async with self._lock:
            if self._user_reset_fence is not None:
                await self._user_reset_fence.require_admission(user_id)
            if self._closed:
                raise ValueError("stage manager is closed")

    async def _require_generation(self, user_id: str, generation: int) -> None:
        if self._user_reset_fence is not None:
            await self._user_reset_fence.require_generation(user_id, generation)

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

    def _remaining_setup_time(self, deadline: float) -> float:
        remaining = deadline - self._monotonic()
        if remaining <= 0:
            raise TimeoutError("call setup timed out")
        return remaining

    def _require_setup_time(self, deadline: float) -> None:
        self._remaining_setup_time(deadline)

    def _existing_call_claim(
        self,
        prepared: PreparedCall,
        *,
        user_id: str,
        character_id: str,
        setup_deadline: float,
    ) -> _CallStartClaim:
        if prepared.user_id != user_id or prepared.character_id != character_id:
            raise ValueError("client_request_id belongs to another call owner")
        prepared.require_live()
        lease = self._lease_registry.current(user_id, character_id)
        if lease is None or (lease.source is InteractionSource.CALL and lease.interaction_id != prepared.call_id):
            raise ValueError("existing call is not owned by this runtime")
        if lease.source is InteractionSource.CALL_TRANSITION and prepared.call_id not in self._handoffs:
            raise ValueError("existing call transition is not owned by this runtime")
        pending = self._call_claims.get(prepared.call_id)
        generation = pending.admission_generation if pending is not None else 0
        return _CallStartClaim(prepared, lease, True, setup_deadline, generation)

    def _take_call_claim(
        self,
        claim: _CallStartClaim,
        *,
        user_id: str,
        character_id: str,
        client_request_id: str,
    ) -> CallStageOwnership:
        """Transfer one validated CALL claim to a future CallStage owner."""
        call_id = str(claim.prepared.call_id)
        if self._call_claims.get(call_id) != claim:
            raise ValueError("call claim is not pending or does not match")
        if (
            claim.prepared.user_id != user_id
            or claim.prepared.character_id != character_id
            or claim.prepared.client_request_id != client_request_id
            or claim.lease.user_id != user_id
            or claim.lease.character_id != character_id
            or claim.setup_deadline != self._call_setup_deadlines.get(client_request_id)
        ):
            raise ValueError("call claim identity mismatch")
        current = self._lease_registry.current(user_id, character_id)
        if current != claim.lease or current.source not in {InteractionSource.CALL, InteractionSource.CALL_TRANSITION}:
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

    def _current_call_ownership(self, call_id: str) -> CallStageOwnership | None:
        return self._call_ownerships.get(call_id)

    async def _create_call_stage(
        self,
        claim: _CallStartClaim,
        *,
        user_id: str,
        character_id: str,
        client_request_id: str,
        config: dict[str, object] | None = None,
        stage_created: Callable[[CallStage], None] | None = None,
        connection_available: bool = True,
        initialize: bool = True,
    ) -> CallStage:
        """Consume a validated claim, then create and register exactly one CallStage."""
        await self._require_generation(user_id, claim.admission_generation)
        operation = self._create_call_stage_owned(
            claim,
            user_id=user_id,
            character_id=character_id,
            client_request_id=client_request_id,
            config=config,
            stage_created=stage_created,
            connection_available=connection_available,
            initialize=initialize,
        )
        if self._user_reset_fence is not None:
            task, _ = await self._user_reset_fence.spawn(user_id, operation, name="call-stage-create")
        else:
            task = asyncio.create_task(operation, name="call-stage-create")
        self._call_stage_creations[task] = user_id
        task.add_done_callback(self._call_stage_creation_done)
        return await asyncio.shield(task)

    async def _create_call_stage_owned(
        self,
        claim: _CallStartClaim,
        *,
        user_id: str,
        character_id: str,
        client_request_id: str,
        config: dict[str, object] | None,
        stage_created: Callable[[CallStage], None] | None,
        connection_available: bool,
        initialize: bool,
    ) -> CallStage:
        await self._require_generation(user_id, claim.admission_generation)
        ownership = self._take_call_claim(
            claim,
            user_id=user_id,
            character_id=character_id,
            client_request_id=client_request_id,
        )
        stage = None
        try:
            if self._call_stage_creator is None:
                raise RuntimeError("CALL_INGRESS_UNAVAILABLE")
            stage = await self._call_stage_creator(
                claim.prepared,
                ownership=ownership,
                own_initialization=partial(self._own_initialization, user_id=user_id, release=self._release_call_stage),
                own_termination=self._own_termination,
                finish_source_interaction=self._finish_source_interaction,
                retention_changed=self._update_retention,
                config=config,
                connection_available=connection_available,
            )
            if stage_created is not None:
                stage_created(stage)
            if initialize:
                await stage.start()
        except BaseException as original_error:
            await self._cleanup_failed_call_stage(
                claim=claim,
                ownership=ownership,
                stage=stage,
                original_error=original_error,
            )
            raise
        await self._require_generation(user_id, claim.admission_generation)
        async with self._lock:
            should_close = self._closed
            if (
                not should_close
                and stage.lifecycle_state not in (StageLifecycleState.TERMINATING, StageLifecycleState.TERMINATED)
                and self._current_call_ownership(ownership.call_id) == ownership
            ):
                self._call_stages[ownership.call_id] = stage
        if should_close:
            await stage.terminate(StageEndReason.SHUTDOWN)
            raise ValueError("stage manager closed during call stage creation")
        return stage

    async def _cleanup_failed_call_stage(self, *, claim, ownership, stage, original_error) -> None:
        if stage is not None:
            await stage.terminate(StageEndReason.INITIALIZATION_FAILED)
            return
        try:
            await self._call_records.abort_start(claim.prepared, original_error)
        except BaseException as cleanup_error:
            self._log_call_cleanup_failure("ledger", claim, original_error, cleanup_error)
        finally:
            handoff = self._handoffs.pop(ownership.call_id, None)
            if handoff is not None:
                await self._restore_chat_after_handoff(handoff.source, handoff.ownership)
            self._call_ownerships.pop(ownership.call_id, None)
            self._call_setup_deadlines.pop(ownership.client_request_id, None)

    @staticmethod
    def _log_call_cleanup_failure(kind, claim, original_error, cleanup_error) -> None:
        get_logger(__name__).error(
            "Call postclaim %s cleanup failed call=%s original_type=%s cleanup_type=%s",
            kind,
            claim.prepared.call_id,
            type(original_error).__name__,
            type(cleanup_error).__name__,
        )

    def _call_stage_creation_done(self, task: asyncio.Task[Any]) -> None:
        self._call_stage_creations.pop(task, None)

    def _release_call_stage_ownership(self, ownership: CallStageOwnership) -> bool:
        if self._call_ownerships.get(ownership.call_id) != ownership:
            return False
        self._call_stages.pop(ownership.call_id, None)
        self._call_stages_by_request.pop(ownership.client_request_id, None)
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
        InteractionConnection | None,
        CallTransitionOwnership | InteractionLease,
    ]:
        async with self._lock:
            if self._closed:
                raise ValueError("stage manager is closed")
            if (user_id, character_id) in self._chat_creations:
                raise ValueError("interaction is already owned")
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
            timer = self._expiry.pop(stage, None)
            if timer is not None:
                timer.cancel()
            stage.set_input_suspended(True)
            return stage, self._connections.get(stage), ownership

    async def _restore_chat_after_handoff(
        self,
        stage: ChatStage | None,
        ownership: CallTransitionOwnership | InteractionLease,
        *,
        refresh_history: bool = False,
    ) -> None:
        if stage is not None and isinstance(ownership, CallTransitionOwnership):
            restored = await stage.restore_after_handoff(
                restore_ownership=partial(self._restore_chat_ownership, stage, ownership),
                refresh_history=refresh_history,
            )
            if restored:
                return
        self._release_transition(ownership)

    async def _restore_chat_ownership(self, stage: ChatStage, ownership: CallTransitionOwnership) -> bool:
        async with self._lock:
            if self._stages.get((stage.user_id, stage.character_id)) is not stage or stage.lifecycle_state in (
                StageLifecycleState.TERMINATING,
                StageLifecycleState.TERMINATED,
            ):
                return False
            self._lease_registry.rollback_call_transition(ownership)
            if self._closed:
                stage.begin_termination(StageEndReason.SHUTDOWN)
            return True

    async def _expire_call_intent(
        self,
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
                stage.set_input_suspended(False)

    def _bound_stage(self, connection: InteractionConnection, character_id: str) -> ChatStage:
        matches = [
            stage
            for stage, current in self._connections.items()
            if current is connection and stage.character_id == character_id
        ]
        if len(matches) != 1:
            raise ValueError("current chat connection is not bound to the character")
        return matches[0]

    async def _disconnect(self, connection: InteractionConnection) -> None:
        async with self._lock:
            for stage, current in list(self._connections.items()):
                if current is connection:
                    self._connections.pop(stage, None)
                    self._schedule_expiry(stage)

    async def _close(self) -> None:
        self._closed = True
        for timer in (*self._expiry.values(), *self._intent_expiry.values()):
            timer.cancel()
        self._expiry.clear()
        self._intent_expiry.clear()
        for entry in tuple(self._managed.values()):
            entry.stage.begin_termination(StageEndReason.SHUTDOWN)
        pending = (
            *self._chat_creations.values(),
            *self._call_open_tasks.values(),
            *self._call_starts.values(),
            *self._call_stage_creations,
        )
        await asyncio.gather(*pending, return_exceptions=True)
        for claim in tuple(self._call_claims.values()):
            await self._call_records.abort_start(claim.prepared, RuntimeError("stage manager closed"))
            handoff = self._handoffs.pop(claim.prepared.call_id, None)
            if handoff is not None:
                self._release_transition(handoff.ownership)
        for entry in tuple(self._managed.values()):
            entry.stage.begin_termination(StageEndReason.SHUTDOWN)
        tasks = tuple(self._terminations.values())
        results = await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.gather(*tuple(self._initializations), return_exceptions=True)
        results.extend(await asyncio.gather(*tuple(self._scope_releases), return_exceptions=True))
        unsafe = [result for result in self._termination_results.values() if not result.resources_released]
        failures = [result for result in results if isinstance(result, BaseException)]
        if unsafe or failures or self._managed:
            raise StageShutdownFailed(f"stage shutdown incomplete: unsafe={len(unsafe)}, failures={len(failures)}")
        self._lease_registry.close()
        self._call_claims.clear()
        self._call_ownerships.clear()
        self._call_setup_deadlines.clear()

    def _update_retention(self, stage: ConnectedStage, deadline: float | None, generation: int) -> None:
        old = self._expiry.pop(stage, None)
        if old is not None and old is not asyncio.current_task():
            old.cancel()
        switching = any(h.source is stage and not h.committed for h in self._handoffs.values())
        if deadline is not None and not self._closed and not switching:
            task = asyncio.create_task(self._expire_retention(stage, deadline, generation), name="stage-offline-expiry")
            self._expiry[stage] = task
            task.add_done_callback(lambda done: None if done.cancelled() else done.exception())

    async def _expire_retention(self, stage: ConnectedStage, deadline: float, generation: int) -> None:
        while self._monotonic() < deadline:
            await asyncio.sleep(deadline - self._monotonic())
        if self._expiry.get(stage) is asyncio.current_task():
            self._expiry.pop(stage, None)
            await stage.expire_retention(deadline, generation)

    def _schedule_expiry(self, stage):
        stage.retain_unbound()
        if stage.offline_deadline is not None:
            self._update_retention(stage, stage.offline_deadline, stage.connection_generation)

    def _start_chat_finalization(self, stage, reason):
        stage.begin_termination(reason)
        return self._terminations[stage.interaction_id]
