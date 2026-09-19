"""WorldStage 使用的事实、计划和无通道输出接收器。"""

from __future__ import annotations

from typing import Protocol

import src.domain.agent as d


class _WorldStagePort(Protocol):
    @property
    def interaction_id(self) -> str: ...

    @property
    def character_id(self) -> str: ...

    def _receive(self, fact: d.Stimulus) -> bool: ...

    def _enqueue_plan(self, plan: d.ActionPlan, token: d.CancellationToken) -> None: ...


class WorldFactSink(Protocol):
    """world 任务向 WorldStage 投递规范化事实的窄端口。"""

    async def submit(self, fact: d.Stimulus) -> bool:
        """提交一个强类型事实；拒绝时返回 False。"""
        ...


class NoChannelOutputSink:
    """明确拒绝没有实时交付通道的世界计划输出。"""

    async def emit(self, output: d.AgentOutput) -> d.OutputReceipt:
        """始终以 SINK_CLOSED 拒绝输出，不把世界输出静默丢弃。"""
        raise d.SinkRejectedError(
            "world stage has no live output channel",
            code=d.SinkRejectionCode.SINK_CLOSED,
        )


class _WorldFactSink:
    def __init__(self, stage: _WorldStagePort) -> None:
        self._stage = stage

    async def submit(self, fact: d.Stimulus) -> bool:
        return self._stage._receive(fact)


class _WorldPlanSink:
    def __init__(self, stage: _WorldStagePort, request: d.HandleStimulusRequest) -> None:
        self._stage, self._request = stage, request
        self.ids: list[str] = []
        self.closed = False

    async def emit(self, plan: d.ActionPlan) -> d.PlanReceipt:
        request, stage = self._request, self._stage
        if self.closed or request.cancellation.is_cancelled:
            raise d.SinkRejectedError(
                "request is stale",
                code=d.SinkRejectionCode.STALE_INTERACTION,
            )
        if (
            plan.origin_request_id != request.request_id
            or plan.interaction_id != stage.interaction_id
            or plan.target_character_id != stage.character_id
            or plan.plan_id in self.ids
            or plan.plan_ordinal != len(self.ids)
        ):
            raise d.SinkRejectedError(
                "plan identity mismatch",
                code=d.SinkRejectionCode.IDENTITY_MISMATCH,
            )
        stage._enqueue_plan(plan, request.cancellation)
        self.ids.append(plan.plan_id)
        return d.PlanReceipt(plan_id=plan.plan_id, status=d.PlanAcceptanceStatus.ACCEPTED)
