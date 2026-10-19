"""通话记录的幂等建立、失败补偿与启动恢复。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4

from src.domain.call import CallEndReason, CallState
from src.infrastructure.persistence.call_sessions import BEIJING_TIMEZONE, CallSessionRecord
from src.utils.owned_operation import complete_owned

from .call_settlement import StaleCallRecoveryService


class CallStartFailed(RuntimeError):
    """保留持久化身份与失败原因，交由 Adapter 生成拒绝响应。"""

    def __init__(self, record):
        self.call_id = str(record.call_id)
        self.end_reason = record.end_reason
        super().__init__("CALL_START_FAILED")


@dataclass(frozen=True, slots=True)
class PreparedCall:
    """已持久化的建立凭据；协调者只读取身份，不操作账本字段。"""

    _record: CallSessionRecord

    @property
    def call_id(self):
        """返回稳定的通话身份。"""
        return str(self._record.call_id)

    @property
    def user_id(self):
        """返回所属用户。"""
        return self._record.user_id

    @property
    def character_id(self):
        """返回所属角色。"""
        return self._record.character_id

    @property
    def client_request_id(self):
        """返回幂等请求身份。"""
        return self._record.client_request_id

    def require_live(self):
        """拒绝已进入终止状态的持久化请求。"""
        if self._record.state in {CallState.FAILED, CallState.ENDING, CallState.ENDED, CallState.DECLINED}:
            self.reject()

    def reject(self):
        """拒绝恢复不存在于当前运行时的旧请求。"""
        raise CallStartFailed(self._record)


class CallRecords:
    """封装通话账本操作，不持有实时资源、Stage 或结算执行器。"""

    def __init__(
        self,
        *,
        call_sessions,
        conversation_service,
        call_maintenance_batches,
        projection_verifier,
        wall_clock,
    ):
        self._call_sessions = call_sessions
        self._wall_clock = wall_clock or (lambda: datetime.now(BEIJING_TIMEZONE))
        self._last_call_timestamp = None
        self._time_lock = asyncio.Lock()
        self._recovery = (
            StaleCallRecoveryService(
                call_sessions=call_sessions,
                conversation_service=conversation_service,
                call_maintenance_batches=call_maintenance_batches,
                projection_verifier=projection_verifier,
            )
            if projection_verifier is not None
            else None
        )
        self._recovery_ready = self._recovery is None

    @property
    def ready(self):
        """返回旧账本恢复是否已经完成。"""
        return self._recovery_ready

    async def initialize(self):
        """在接入前收敛遗留账本，失败时保持不可用。"""
        if self._recovery_ready:
            return
        report = await self._recovery.reconcile()
        if report.failed or report.conflicted:
            raise RuntimeError("stale call recovery did not converge")
        self._recovery_ready = True

    async def find_start(self, client_request_id, *, user_id, character_id):
        """读取并验证幂等请求身份，不尝试复活持久化交互。"""
        if self._call_sessions is None:
            return None
        record = await self._repository_call(self._call_sessions.find_by_request, client_request_id)
        if record is None:
            return None
        if record.user_id != user_id or record.character_id != character_id:
            raise ValueError("client_request_id belongs to another call owner")
        return PreparedCall(record)

    async def prepare_start(self, *, user_id, character_id, client_request_id):
        """建立 PREPARING 记录，成功后才允许协调者提交聊天退出。"""
        if self._call_sessions is None:
            raise RuntimeError("call session repository is not bound")
        record = await self._new_call_record(user_id, character_id, client_request_id)
        record = await self._repository_call(self._call_sessions.create_if_absent, record)
        if record.user_id != user_id or record.character_id != character_id:
            raise ValueError("call request resolved to another owner")
        prepared = PreparedCall(record)
        prepared.require_live()
        return prepared

    async def abort_start(self, prepared, error):
        """持久化建立失败；交互占用必须在此补偿停止后释放。"""
        await self._mark_call_failed(prepared._record, error)

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

    @staticmethod
    async def _repository_call(operation, *args, **kwargs):
        """Run one synchronous repository operation to completion outside the event loop."""
        return await complete_owned(asyncio.to_thread(operation, *args, **kwargs))
