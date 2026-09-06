"""本次处理的草稿封装、持久投递及原计划恢复。"""
import asyncio
from dataclasses import dataclass, replace

import src.domain.agent as d
from src.agent.ledgers.plan_outbox import PlanSlot
from src.utils.logger import get_logger
from .identity import plan_id


class _DeliveryCancelled(Exception):
    """协作取消，与调用任务取消分开处理。"""


class PlanStorageError(RuntimeError):
    """保存投递事实失败，公开报告映射依赖不可用。"""


def _check_cancellation(token):
    if token.is_cancelled:
        raise _DeliveryCancelled()


def handling_error(error):
    if isinstance(error, PlanStorageError):
        return d.HandlingErrorCode.DEPENDENCY_UNAVAILABLE
    if isinstance(error, d.SinkRejectedError) and error.code.name in {
            "STALE_INTERACTION", "SINK_CLOSED", "BACKPRESSURE_TIMEOUT"}:
        return d.HandlingErrorCode[error.code.name]
    return d.HandlingErrorCode.PROVIDER_TIMEOUT if isinstance(error, TimeoutError) else d.HandlingErrorCode.INTERNAL_ERROR


@dataclass(frozen=True, slots=True, kw_only=True)
class ActionPlanDraft:
    """处理器提交的不可变来源和行动；emit 时按完整计划约束校验。"""
    source_stimulus_ids: tuple[str, ...]
    actions: tuple[d.Action, ...]


class PlanEmitter:
    """分配稳定计划身份，先保存后交付，仅保存有效回执确认。"""

    def __init__(self, character_id, request, sink, outbox, *, recovery=False):
        self._character_id, self._request, self._sink = character_id, request, sink
        self._outbox, self._lock = outbox, asyncio.Lock()
        self._slots = self._stored(outbox.load, request.request_id) if recovery else []
        self._error = None
        for slot in self._slots:
            self._validate(slot.plan)

    @property
    def accepted_ids(self):
        """按槽位返回真实确认身份；不会把未知投递当作已接收。"""
        return [slot.plan.plan_id for slot in self._slots if slot.confirmed]

    @staticmethod
    def _stored(operation, *args):
        try:
            return operation(*args)
        except Exception as error:
            raise PlanStorageError("plan storage unavailable") from error

    def _validate(self, plan):
        request = self._request
        sources = {s.stimulus_id for s in (request.stimulus, *request.interaction.pending_stimuli)}
        if (plan.interaction_id != request.interaction.interaction_id
                or plan.basis_interaction_revision != request.interaction.interaction_revision
                or not set(plan.source_stimulus_ids).issubset(sources)):
            raise ValueError("plan does not match request")

    async def emit(self, draft: ActionPlanDraft, *, ordinal: int | None = None) -> d.PlanReceipt:
        """串行封装并交付；同槽位同值可重试，已确认重投仅返回本地回执。

        错误草稿、冲突或非法槽位抛异常；存储失败不交付，调用结束后抛 RuntimeError。
        """
        async with self._lock:
            if self._sink is None:
                raise RuntimeError("plan emitter is closed")
            _check_cancellation(self._request.cancellation)
            selected = len(self._slots) if ordinal is None else ordinal
            try:
                if (type(draft) is not ActionPlanDraft or type(selected) is not int or selected < 0
                        or (ordinal is not None and selected >= len(self._slots))):
                    raise ValueError("invalid draft or ordinal")
                plan = d.ActionPlan(plan_id=plan_id(self._character_id, self._request.request_id, selected),
                    origin_request_id=self._request.request_id, plan_ordinal=selected,
                    target_character_id=self._character_id, interaction_id=self._request.interaction.interaction_id,
                    basis_interaction_revision=self._request.interaction.interaction_revision,
                    source_stimulus_ids=draft.source_stimulus_ids, actions=draft.actions)
                self._validate(plan)
                if ordinal is None:
                    if any(slot.state != "accepted" for slot in self._slots):
                        raise ValueError("unresolved plan blocks next slot")
                    slot = PlanSlot(plan)
                    self._stored(self._outbox.save, slot)
                    self._slots.append(slot)
                else:
                    slot = self._slots[selected]
                    if slot.plan != plan or slot.state == "rejected":
                        raise ValueError("plan slot conflict")
                if slot.confirmed:
                    return d.PlanReceipt(plan_id=plan.plan_id, status=d.PlanAcceptanceStatus.ALREADY_ACCEPTED)
                return await self._send(slot)
            except _DeliveryCancelled:
                raise
            except Exception as error:
                self._failed(error, selected)
                raise

    async def _send(self, slot):
        _check_cancellation(self._request.cancellation)
        previous = slot.outcome
        self._stored(self._outbox.mark, slot, "pending", "unknown")
        try:
            receipt = await self._sink.emit(slot.plan)
        except d.SinkRejectedError as error:
            state = "pending" if error.code is d.SinkRejectionCode.BACKPRESSURE_TIMEOUT else "rejected"
            self._stored(self._outbox.mark, slot, state, "unknown" if previous == "unknown" else "rejected")
            raise
        if not isinstance(receipt, d.PlanReceipt) or receipt.plan_id != slot.plan.plan_id:
            raise ValueError("invalid plan receipt")
        slot.confirmed = True
        self._stored(self._outbox.mark, slot, "accepted", "accepted")
        self._error = None
        _check_cancellation(self._request.cancellation)
        return receipt

    async def recover(self):
        """仅重投未确认的原计划；处理器不会重新运行，异常留给门面结算。"""
        for slot in self._slots:
            if slot.state == "pending":
                try:
                    await self._send(slot)
                except _DeliveryCancelled:
                    raise
                except Exception as error:
                    self._failed(error, slot.plan.plan_ordinal)
                    raise

    def finish(self, report, *, recovery=False):
        """保留可信认知消费，覆盖未完成投递状态；恢复不宣称认知成功。"""
        pending = any(slot.state == "pending" and not slot.confirmed for slot in self._slots)
        changes = dict(emitted_plan_ids=tuple(self.accepted_ids))
        if self._error is not None:
            changes.update(request_status=d.HandlingRequestStatus.FAILED, error_code=self._error, retryable=pending)
        elif recovery:
            changes["retryable"] = pending
        return replace(report, **changes)

    def _failed(self, error, ordinal):
        self._error = handling_error(error)
        safe_error = RuntimeError("Collaborator exception message omitted")
        get_logger(__name__).error(
            "Plan delivery failed character_id=%s request_id=%s interaction_id=%s plan_id=%s ordinal=%s error_code=%s type=%s",
            self._character_id, self._request.request_id, self._request.interaction.interaction_id,
            plan_id(self._character_id, self._request.request_id, ordinal), ordinal, self._error.name,
            type(error).__name__, exc_info=(RuntimeError, safe_error, error.__traceback__))

    def close(self):
        """结束本次作用域并释放接收器及请求引用。"""
        self._sink = self._request = None
