"""单次刺激的处理器路由、计划交付和处理报告校验。"""
import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING

import src.domain.agent as d
from .plan_emitter import PlanEmitter, _DeliveryCancelled
from .invocation import call_handler

if TYPE_CHECKING:
    from src.agent.facade import Agent


class Handling:
    """管理一次刺激处理，处理结束后关闭本次计划交付器。"""

    def __init__(self, agent: "Agent", request: d.HandleStimulusRequest,
                 sink: d.ActionPlanSink) -> None:
        """绑定角色门面、当前请求及本次计划接收器。"""
        self.agent, self.request, self.sink = agent, request, sink

    async def run(self) -> d.HandlingReport:
        """检查取消状态并选择处理器，交付计划后返回本次处理报告。"""
        request = self.request
        status, error = d.HandlingRequestStatus.FAILED, None
        if request.cancellation.is_cancelled:
            status = d.HandlingRequestStatus.CANCELLED
            return self.agent._handling_failure(request, status, error)
        try:
            handler = self.agent._stimulus_router.resolve(request.stimulus.kind)
        except KeyError:
            error = d.HandlingErrorCode.UNSUPPORTED_STIMULUS
            return self.agent._handling_failure(request, status, error)

        plan_emitter = PlanEmitter(self.agent._character_id, request, self.sink)
        try:
            try:
                report = await call_handler(
                    self.agent,
                    lambda: handler.handle(request, plan_emitter),
                    request.cancellation,
                    request.request_id,
                    request.interaction.interaction_id,
                )
                self._validate_handling_report(request, report, plan_emitter.accepted_ids)
                if request.cancellation.is_cancelled:
                    report = replace(report, request_status=d.HandlingRequestStatus.CANCELLED, error_code=None, retryable=False)
            except _DeliveryCancelled:
                report = self.agent._handling_failure(request, d.HandlingRequestStatus.CANCELLED, None, plan_emitter.accepted_ids)
            except Exception as error:
                code = self.agent._error_code(error, d.HandlingErrorCode)
                self.agent._record_exception(request.request_id, request.interaction.interaction_id, code, error)
                report = self.agent._handling_failure(request, d.HandlingRequestStatus.FAILED, code, plan_emitter.accepted_ids)
            return plan_emitter.finish(report)
        except asyncio.CancelledError:
            self.agent._record(request.request_id, request.interaction.interaction_id, d.HandlingRequestStatus.CANCELLED, None)
            raise
        finally:
            plan_emitter.close()

    @staticmethod
    def _validate_handling_report(request: d.HandleStimulusRequest, report: d.HandlingReport, accepted_ids: list[str]) -> None:
        pending = tuple(item.stimulus_id for item in request.interaction.pending_stimuli)
        if (
            not isinstance(report, d.HandlingReport)
            or report.request_id != request.request_id
            or report.trigger_stimulus_id != request.stimulus.stimulus_id
            or report.basis_interaction_revision != request.interaction.interaction_revision
            or report.emitted_plan_ids != tuple(accepted_ids)
            or tuple(i for i in pending if i in report.considered_pending_stimulus_ids) != report.considered_pending_stimulus_ids
        ):
            raise ValueError("invalid handler settlement")
