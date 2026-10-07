"""世界事实的结算分发：把 WorldStage 的处理与执行结果交回投递该事实的任务。

world 任务在投递事实前登记订阅者，WorldStage 的处理结算与计划执行结算都经这里按刺激 ID 分派。
订阅者因此不需要读取 Stage 内部状态，也不需要轮询自己的存储来判断「Agent 到底做了什么」。

订阅者失败只被记录与计数，不允许破坏 Stage 的结算流程；未匹配的结算同样只计数，不抛异常。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import src.domain.agent as d
from src.utils.logger import get_logger


@dataclass(frozen=True)
class FactHandlingOutcome:
    """一次事实处理的结果；未产生计划时 plan_ids 为空。"""

    stimulus_id: str
    request_status: d.HandlingRequestStatus
    consumed: bool
    error_code: d.HandlingErrorCode | None
    plan_ids: tuple[str, ...]

    @property
    def ignored(self) -> bool:
        """是否被明确处理但未产生任何效果计划（例如「决定不回复」）。"""
        return (self.request_status is d.HandlingRequestStatus.COMPLETED
                and self.consumed and not self.plan_ids)


@dataclass(frozen=True)
class FactPlanOutcome:
    """该事实触发的一个计划及其执行结果，含已提交效果。"""

    stimulus_id: str
    plan: d.ActionPlan
    report: d.ExecutionReport

    @property
    def effect_refs(self) -> tuple[d.EffectRef, ...]:
        """本次执行已提交的效果引用（未提交的项没有引用）。"""
        return tuple(
            item.effect_ref for item in self.report.action_results if item.effect_ref is not None
        )


class FactSettlementSubscriber(Protocol):
    """接收自己投递的事实的结算回执。"""

    def on_fact_handled(self, outcome: FactHandlingOutcome) -> None:
        """处理结算：该事实是否被消费、是否产生计划以及失败原因。"""
        ...

    def on_fact_plan_executed(self, outcome: FactPlanOutcome) -> None:
        """执行结算：该事实产生的某个计划的结果与已提交效果。"""
        ...


class WorldSettlementRouter:
    """按刺激 ID 把 Stage 结算分派给投递方，不解释事实内容。"""

    def __init__(self) -> None:
        self._logger = get_logger(__name__)
        self._subscribers: dict[str, FactSettlementSubscriber] = {}
        self._pending_plans: dict[str, int] = {}
        self._unmatched = 0
        self._failures = 0

    @property
    def unmatched_settlements(self) -> int:
        """未被任何订阅者认领的结算次数。"""
        return self._unmatched

    @property
    def subscriber_failures(self) -> int:
        """订阅者自身抛错的次数；已记录，不影响 Stage。"""
        return self._failures

    @property
    def awaiting_settlement(self) -> tuple[str, ...]:
        """仍在等待结算的刺激 ID。"""
        return tuple(self._subscribers)

    def register(self, stimulus_id: str, subscriber: FactSettlementSubscriber) -> None:
        """登记投递方；stimulus_id 为空或已登记时抛错。"""
        if not isinstance(stimulus_id, str) or not stimulus_id.strip():
            raise ValueError("stimulus_id 不能为空")
        if stimulus_id in self._subscribers:
            raise ValueError("该事实已登记订阅者")
        self._subscribers[stimulus_id] = subscriber

    def discard(self, stimulus_id: str) -> None:
        """撤销登记（投递被拒或不再关心该事实）；重复调用幂等。"""
        self._subscribers.pop(stimulus_id, None)
        self._pending_plans.pop(stimulus_id, None)

    def on_handling_settled(
        self, request: d.HandleStimulusRequest, report: d.HandlingReport,
    ) -> None:
        """WorldStage 处理结算回调：先分派处理结果，再按计划数登记执行结算。"""
        stimulus_id = report.trigger_stimulus_id
        subscriber = self._subscribers.get(stimulus_id)
        if subscriber is None:
            self._unmatched += 1
            return
        self._notify(subscriber.on_fact_handled, FactHandlingOutcome(
            stimulus_id=stimulus_id,
            request_status=report.request_status,
            consumed=stimulus_id in report.consumed_pending_stimulus_ids,
            error_code=report.error_code,
            plan_ids=report.emitted_plan_ids,
        ))
        if report.emitted_plan_ids:
            self._pending_plans[stimulus_id] = len(report.emitted_plan_ids)
        else:
            self.discard(stimulus_id)

    def on_execution_finished(self, plan: d.ActionPlan, report: d.ExecutionReport) -> None:
        """WorldStage 计划执行结算回调：按来源刺激分派，最后一个计划后撤销登记。"""
        matched = False
        for stimulus_id in plan.source_stimulus_ids:
            subscriber = self._subscribers.get(stimulus_id)
            if subscriber is None:
                continue
            matched = True
            self._notify(subscriber.on_fact_plan_executed, FactPlanOutcome(stimulus_id, plan, report))
            remaining = self._pending_plans.get(stimulus_id, 0) - 1
            if remaining > 0:
                self._pending_plans[stimulus_id] = remaining
            else:
                self.discard(stimulus_id)
        if not matched:
            self._unmatched += 1

    def _notify(self, callback: Callable[..., None], outcome: object) -> None:
        try:
            callback(outcome)
        except Exception:
            self._failures += 1
            self._logger.exception(
                "世界事实结算订阅者失败 stimulus=%s", getattr(outcome, "stimulus_id", ""),
            )
