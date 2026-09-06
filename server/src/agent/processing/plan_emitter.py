"""本次处理的草稿封装和顺序交付。"""
import asyncio
from dataclasses import dataclass, replace
from traceback import walk_tb

import src.domain.agent as d
from src.utils.logger import get_logger
from .plan_identity import encode_plan, plan_id


class _DeliveryCancelled(Exception):
    """协作取消，与调用任务取消分开处理。"""


def _check_cancellation(token):
    if token.is_cancelled:
        raise _DeliveryCancelled()


def handling_error(error):
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
    """为本次调用分配计划序号，顺序交付并记录已确认接收的计划标识。"""

    def __init__(self, character_id: str, request: d.HandleStimulusRequest,
                 sink: d.ActionPlanSink) -> None:
        """绑定角色、请求和本次调用使用的计划接收器。"""
        self._character_id, self._request, self._sink = character_id, request, sink
        self._lock = asyncio.Lock()
        self._accepted_ids: list[str] = []
        self._error = None
        self._failure = None

    @property
    def accepted_ids(self) -> list[str]:
        """按交付顺序返回本次已确认接收的计划标识副本。"""
        return list(self._accepted_ids)

    def _validate(self, plan):
        request = self._request
        sources = {s.stimulus_id for s in (request.stimulus, *request.interaction.pending_stimuli)}
        if (plan.interaction_id != request.interaction.interaction_id
                or plan.basis_interaction_revision != request.interaction.interaction_revision
                or not set(plan.source_stimulus_ids).issubset(sources)):
            raise ValueError("plan does not match request")

    async def emit(self, draft: ActionPlanDraft) -> d.PlanReceipt:
        """将行动草稿封装为下一份计划并交付；首次失败后拒绝继续交付。"""
        async with self._lock:
            if self._sink is None:
                raise RuntimeError("plan emitter is closed")
            if self._failure is not None:
                raise self._failure
            _check_cancellation(self._request.cancellation)
            selected = len(self._accepted_ids)
            try:
                if type(draft) is not ActionPlanDraft:
                    raise ValueError("invalid plan draft")
                plan = d.ActionPlan(
                    plan_id=plan_id(self._character_id, self._request.request_id, selected),
                    origin_request_id=self._request.request_id, plan_ordinal=selected,
                    target_character_id=self._character_id,
                    interaction_id=self._request.interaction.interaction_id,
                    basis_interaction_revision=self._request.interaction.interaction_revision,
                    source_stimulus_ids=draft.source_stimulus_ids, actions=draft.actions)
                self._validate(plan)
                encode_plan(plan)
                receipt = await self._sink.emit(plan)
                if not isinstance(receipt, d.PlanReceipt) or receipt.plan_id != plan.plan_id:
                    raise ValueError("invalid plan receipt")
                self._accepted_ids.append(plan.plan_id)
                _check_cancellation(self._request.cancellation)
                return receipt
            except _DeliveryCancelled:
                raise
            except asyncio.CancelledError as error:
                self._failure = error
                raise
            except Exception as error:
                self._failure = error
                self._failed(error, selected)
                raise

    def finish(self, report: d.HandlingReport) -> d.HandlingReport:
        """保留处理结果和已接收计划；交付失败时将报告标记为失败且不可重试。"""
        changes = dict(emitted_plan_ids=tuple(self.accepted_ids), retryable=False)
        if isinstance(self._failure, asyncio.CancelledError):
            changes.update(request_status=d.HandlingRequestStatus.CANCELLED, error_code=None)
        elif self._error is not None:
            changes.update(request_status=d.HandlingRequestStatus.FAILED, error_code=self._error)
        return replace(report, **changes)

    def _failed(self, error, ordinal):
        """保存投递失败；日志只携带身份、错误类型及栈位置，隔离源码和异常链。"""
        self._error = handling_error(error)
        locations = [(frame.f_code.co_filename, line, frame.f_code.co_name)
                     for frame, line in walk_tb(error.__traceback__)]
        get_logger(__name__).error(
            "Plan delivery failed character_id=%s request_id=%s interaction_id=%s plan_id=%s ordinal=%s error_code=%s type=%s stack=%s",
            self._character_id, self._request.request_id, self._request.interaction.interaction_id,
            plan_id(self._character_id, self._request.request_id, ordinal), ordinal, self._error.name,
            type(error).__name__, locations)

    def close(self):
        """结束本次作用域并释放接收器及请求引用。"""
        self._sink = self._request = None
