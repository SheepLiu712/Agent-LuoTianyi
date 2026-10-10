"""管理聊天 Stage 的创建、重连保留和离线回收。"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
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


@dataclass(frozen=True, slots=True)
class CallStageOwnership:
    call_id: str
    user_id: str
    character_id: str
    client_request_id: str
    setup_deadline: float
    generation: int


class StageManager:
    """按用户与角色管理 Stage，持有共享 adapter 及离线回收任务。"""

    def __init__(
        self,
        *,
        get_agent: Callable[[str], Agent],
        adapter: WebSocketAdapter,
        get_context_factory: Callable[[str], ContextFactory],
        due_event_provider: DueEventProvider | None = None,
        lease_registry: InteractionLeaseRegistry | None = None,
        call_sessions: CallSessionRepository | None = None,
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
        self._wall_clock = wall_clock or (lambda: datetime.now(BEIJING_TIMEZONE))
        self._monotonic = monotonic
        self._last_call_timestamp: datetime | None = None
        self._time_lock = asyncio.Lock()
        self._stages: dict[tuple[str, str], ChatStage] = {}
        self._connections: dict[ChatStage, WebSocketConnection] = {}
        self._expiry: dict[ChatStage, asyncio.Task[None]] = {}
        self._retiring: set[asyncio.Task[None]] = set()
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
        self._call_stage_creations: set[asyncio.Task[Any]] = set()
        self._call_ownership_generation = 0
        self._intent_expiry: dict[tuple[str, str], asyncio.Task[None]] = {}

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

    async def _connect(self, connection: WebSocketConnection, character_id: str) -> ChatStage:
        async with self._lock:
            if self._closed or connection.is_closed or not connection.user_uuid:
                raise ValueError("manager or connection is unavailable")
            key = (connection.user_uuid, character_id)
            stage = self._stages.get(key)
            if stage is None or stage.state in (StageState.TERMINATING, StageState.TERMINATED):
                if stage is not None:
                    self._lease_registry.release(
                        InteractionLease(
                            stage.user_id, stage.character_id, stage.interaction_id, InteractionSource.CHAT
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

    async def prepare_call_transition(
        self,
        connection: WebSocketConnection,
        *,
        character_id: str,
        client_request_id: str,
    ) -> CallTransitionIntent:
        """Prepare a one-shot transition only from the currently bound chat connection."""
        async with self._lock:
            stage = self._bound_stage(connection, character_id)
            lease = InteractionLease(stage.user_id, stage.character_id, stage.interaction_id, InteractionSource.CHAT)
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

    async def start_call(
        self,
        *,
        user_id: str,
        character_id: str,
        source_interaction_id: str | None,
        client_request_id: str,
    ) -> CallStartClaim:
        """Persist PREPARING, retire chat, close its context, then transfer ownership to CALL."""
        task = self._call_starts.get(client_request_id)
        operation = (user_id, character_id, source_interaction_id)
        current_operation = self._call_start_operations.get(client_request_id)
        if current_operation is not None and current_operation != operation:
            raise ValueError("client_request_id is already starting another call")
        if task is None:
            deadline = self._call_setup_deadlines.setdefault(
                client_request_id,
                self._monotonic() + self._config.call_setup_timeout,
            )
            task = asyncio.create_task(
                self._start_call(
                    user_id=user_id,
                    character_id=character_id,
                    source_interaction_id=source_interaction_id,
                    client_request_id=client_request_id,
                    setup_deadline=deadline,
                ),
                name="call-handoff",
            )
            self._call_starts[client_request_id] = task
            self._call_start_operations[client_request_id] = operation
            task.add_done_callback(lambda finished, key=client_request_id: self._call_start_done(key, finished))
        return await complete_owned(self._await_call_start(task))

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

    async def _start_call(
        self,
        *,
        user_id: str,
        character_id: str,
        source_interaction_id: str | None,
        client_request_id: str,
        setup_deadline: float,
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
        async with self._lock:
            if self._closed:
                raise ValueError("stage manager is closed")
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
                if self._closed:
                    raise RuntimeError("stage manager closed during call handoff")
            call_lease = self._finish_transition(ownership, call_id=str(record.call_id))
            claim = CallStartClaim(record, call_lease, False, deadline)
            self._call_claims[str(record.call_id)] = claim
            return claim
        except BaseException as error:
            await self._cleanup_postledger_failure(record, stage, ownership, error)
            raise

    async def _commit_chat_handoff(self, stage: ChatStage, *, user_id: str, character_id: str) -> None:
        async with self._lock:
            if self._closed:
                raise RuntimeError("stage manager closed during call handoff")
            self._stages.pop((user_id, character_id), None)
            timer = self._expiry.pop(stage, None)
            if timer is not None:
                timer.cancel()
            self._connections.pop(stage, None)

    async def _terminate_for_call(self, stage: ChatStage, deadline: float) -> None:
        remaining = self._remaining_setup_time(deadline)
        termination = asyncio.create_task(
            stage.terminate(InteractionEndingReason.SWITCH_TO_CALL), name="chat-call-terminate"
        )
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
            await complete_owned(stage.terminate(InteractionEndingReason.SWITCH_TO_CALL))
        self._release_transition(ownership)
        try:
            await self._mark_call_failed(record, original_error)
        except Exception as cleanup_error:  # noqa: BLE001 - preserve original failure and report cleanup loss
            get_logger(__name__).error(
                "Failed to mark call ledger failed call=%s original=%s cleanup=%s",
                record.call_id,
                original_error,
                cleanup_error,
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
        lease = self._lease_registry.current(user_id, character_id)
        if lease is None or lease.source is not InteractionSource.CALL or lease.interaction_id != str(record.call_id):
            raise ValueError("existing call is not owned by this runtime")
        return CallStartClaim(record, lease, True, setup_deadline)

    def take_call_claim(
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

    def current_call_ownership(self, call_id: str) -> CallStageOwnership | None:
        return self._call_ownerships.get(call_id)

    def current_call_stage(self, call_id: str) -> CallStage | None:
        """Return the runtime CallStage currently bound to this call identity."""
        return self._call_stages.get(call_id)

    async def create_call_stage(
        self,
        claim: CallStartClaim,
        *,
        user_id: str,
        character_id: str,
        client_request_id: str,
        speech_factory: RealtimeSpeechSessionFactory,
        transport: CallTransportSink,
        settlement_sink: Any | None = None,
        config: dict[str, object] | None = None,
    ) -> CallStage:
        """Consume a validated claim, then create and register exactly one CallStage."""
        async with self._lock:
            if self._closed:
                raise ValueError("stage manager is closed")
        task = asyncio.create_task(
            self._create_call_stage(
                claim,
                user_id=user_id,
                character_id=character_id,
                client_request_id=client_request_id,
                speech_factory=speech_factory,
                transport=transport,
                settlement_sink=settlement_sink,
                config=config,
            ),
            name="call-stage-create",
        )
        self._call_stage_creations.add(task)
        task.add_done_callback(self._call_stage_creations.discard)
        return await asyncio.shield(task)

    async def _create_call_stage(
        self,
        claim: CallStartClaim,
        *,
        user_id: str,
        character_id: str,
        client_request_id: str,
        speech_factory: RealtimeSpeechSessionFactory,
        transport: CallTransportSink,
        settlement_sink: Any | None,
        config: dict[str, object] | None,
    ) -> CallStage:
        from .call_stage import CallStage

        ownership = self.take_call_claim(
            claim,
            user_id=user_id,
            character_id=character_id,
            client_request_id=client_request_id,
        )
        if self._call_sessions is None:
            self.release_call(ownership)
            raise RuntimeError("call session repository is not bound")
        try:
            stage = await CallStage.create(
                ownership=ownership,
                record=claim.record,
                agent=self._get_agent(character_id),
                context_factory=self._get_context_factory(character_id),
                call_sessions=self._call_sessions,
                speech_factory=speech_factory,
                transport=transport,
                release_ownership=self._release_call_stage_ownership,
                settlement_sink=settlement_sink,
                monotonic=self._monotonic,
                wall_clock=self._wall_clock,
                config=config,
            )
        except BaseException:
            self.release_call(ownership)
            raise
        async with self._lock:
            if self._closed:
                await stage.close()
                raise ValueError("stage manager closed during call stage creation")
            if stage.snapshot is None and self.current_call_ownership(ownership.call_id) == ownership:
                self._call_stages[ownership.call_id] = stage
        return stage

    def _release_call_stage_ownership(self, ownership: CallStageOwnership) -> bool:
        self._call_stages.pop(ownership.call_id, None)
        return self.release_call(ownership)

    def release_call(self, ownership: CallStageOwnership) -> bool:
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
    ) -> tuple[ChatStage | None, WebSocketConnection | None, CallTransitionOwnership | InteractionLease]:
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
        failed = record.with_update(
            state=CallState.FAILED,
            end_reason=end_reason,
            updated_at=await self._next_call_timestamp(),
        )
        assert self._call_sessions is not None
        await self._repository_call(
            self._call_sessions.update_if_state,
            record.call_id,
            expected_state=CallState.PREPARING,
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
            stages = tuple(self._stages.values())
            self._stages.clear()
            timers = tuple(self._expiry.values())
            self._expiry.clear()
            for timer in timers:
                timer.cancel()
            intent_timers = tuple(self._intent_expiry.values())
            self._intent_expiry.clear()
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
            await self._retire(stage, InteractionEndingReason.SHUTDOWN)
        call_stages = tuple(self._call_stages.values())
        if call_stages:
            await asyncio.gather(*(stage.close() for stage in call_stages), return_exceptions=True)
        self._call_stages.clear()
        if self._retiring:
            await asyncio.gather(*tuple(self._retiring), return_exceptions=True)
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
            self._lease_registry.release(
                InteractionLease(stage.user_id, stage.character_id, stage.interaction_id, InteractionSource.CHAT)
            )
            # 从可复用集合移除后才开始结束处理；重连可创建新的交互。
            task = asyncio.create_task(self._retire(stage, InteractionEndingReason.USER_LEFT), name="stage-retire")
            self._retiring.add(task)
            task.add_done_callback(self._retiring.discard)

    async def _retire(self, stage: ChatStage, reason: InteractionEndingReason) -> None:
        try:
            result = await stage.terminate(reason)
            if result.error is not None:
                get_logger(__name__).error(
                    "Stage retirement failed interaction=%s error=%s", stage.interaction_id, result.error
                )
        finally:
            await self._adapter.disconnect(stage)
            self._connections.pop(stage, None)
            self._lease_registry.release(
                InteractionLease(stage.user_id, stage.character_id, stage.interaction_id, InteractionSource.CHAT)
            )
