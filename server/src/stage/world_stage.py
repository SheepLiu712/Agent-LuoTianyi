"""按角色与世界长期持有的事实处理和计划执行通道。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING, final
from uuid import uuid4
from zoneinfo import ZoneInfo

import src.domain.agent as d
from src.agent.context import ContextFactory, InteractionContext
from src.agent.handlers.stimulus.world_activity import WORLD_ACTIVITY_STIMULUS_KINDS
from src.domain.stage import StageState
from src.utils.logger import get_logger

from ._config import _StageConfig
from ._world_sinks import (
    NoChannelOutputSink,
    WorldFactSink,
    _WorldFactSink,
    _WorldPlanSink,
)

if TYPE_CHECKING:
    from src.agent.facade import Agent


ExecutionFinishedCallback = Callable[[d.ActionPlan, d.ExecutionReport], None]
HandlingSettledCallback = Callable[[d.HandleStimulusRequest, d.HandlingReport], None]


@final
class WorldStage:
    """长期协调一个角色在一个世界中的事实处理与串行计划执行。"""

    def __init__(
        self,
        *,
        character_id: str,
        world_id: str,
        agent: Agent,
        context: InteractionContext,
        config: dict[str, int | float] | None = None,
        timezone_name: str = "Asia/Shanghai",
        on_execution_finished: ExecutionFinishedCallback | None = None,
        on_handling_settled: HandlingSettledCallback | None = None,
    ) -> None:
        if any(not isinstance(value, str) or not value.strip() for value in (character_id, world_id)):
            raise ValueError("character_id and world_id must be nonblank")
        if context.identity.character_id != character_id or context.identity.user_id is not None:
            raise ValueError("context identity does not match world stage")
        self._character_id, self._world_id = character_id, world_id
        self._agent, self._context = agent, context
        self._interaction_id = context.identity.interaction_id
        self._config = _StageConfig.from_dict({} if config is None else config)
        self._timezone = ZoneInfo(timezone_name)
        self._state = StageState.ONLINE
        self._revision = 0
        self._world_revision = 0
        self._activity_id: str | None = None
        self._activity_revision: int | None = None
        self._planning_cycle_id: str | None = None
        self._schedule_revision = 0
        self._pending: dict[str, d.Stimulus] = {}
        self._requests: dict[str, d.HandleStimulusRequest] = {}
        self._handles: dict[str, asyncio.Task[None]] = {}
        self._plans: asyncio.Queue[tuple[d.ActionPlan, d.CancellationToken]] = asyncio.Queue(
            maxsize=self._config.max_plans,
        )
        self._execution: d.ExecutionContext | None = None
        self._output_sink = NoChannelOutputSink()
        self._on_execution_finished = on_execution_finished
        self._on_handling_settled = on_handling_settled
        self._fact_sink = _WorldFactSink(self)
        self._closed = asyncio.Event()
        self._worker = asyncio.create_task(self._execution_worker(), name="world-stage-execution")
        self._logger = get_logger(__name__)

    @classmethod
    async def create(
        cls,
        *,
        character_id: str,
        world_id: str,
        agent: Agent,
        context_factory: ContextFactory,
        config: dict[str, int | float] | None = None,
        timezone_name: str = "Asia/Shanghai",
        on_execution_finished: ExecutionFinishedCallback | None = None,
        on_handling_settled: HandlingSettledCallback | None = None,
    ) -> WorldStage:
        """创建并接管无用户世界上下文；构造失败时关闭上下文。"""
        context = await context_factory.create(str(uuid4()), user_id=None)
        try:
            return cls(
                character_id=character_id,
                world_id=world_id,
                agent=agent,
                context=context,
                config=config,
                timezone_name=timezone_name,
                on_execution_finished=on_execution_finished,
                on_handling_settled=on_handling_settled,
            )
        except BaseException:
            await context.close()
            raise

    @property
    def fact_sink(self) -> WorldFactSink:
        return self._fact_sink

    @property
    def interaction_id(self) -> str:
        return self._interaction_id

    @property
    def interaction_revision(self) -> int:
        return self._revision

    @property
    def character_id(self) -> str:
        return self._character_id

    @property
    def world_id(self) -> str:
        return self._world_id

    @property
    def state(self) -> StageState:
        return self._state

    @property
    def pending_stimuli(self) -> tuple[d.Stimulus, ...]:
        return tuple(self._pending.values())

    @property
    def execution_worker(self) -> asyncio.Task[None]:
        return self._worker

    def _receive(self, fact: d.Stimulus) -> bool:
        if (
            not isinstance(fact, d.Stimulus)
            or self._state is not StageState.ONLINE
            or fact.source is not d.StimulusSource.WORLD
            or fact.user_id is not None
            or self.character_id not in fact.target_character_ids
            or fact.kind not in WORLD_ACTIVITY_STIMULUS_KINDS
            or fact.stimulus_id in self._pending
            or len(self._pending) >= self._config.max_stimuli
            or len(self._handles) >= self._config.max_stimuli
            or not self._owner_revision_is_current(fact)
        ):
            return False
        self._revision += 1
        self._apply_owner_revision(fact)
        self._pending[fact.stimulus_id] = fact
        request = d.HandleStimulusRequest(
            request_id=str(uuid4()),
            stimulus=fact,
            interaction=self._snapshot(),
            cancellation=d.CancellationToken(),
            prepared_inputs=(),
            purpose=d.HandlePurpose.PROCESS,
        )
        self._requests[request.request_id] = request
        task = asyncio.create_task(self._handle(request), name="world-stage-handle")
        self._handles[request.request_id] = task
        task.add_done_callback(lambda done: self._handle_done(request.request_id, done))
        return True

    def _owner_revision_is_current(self, fact: d.Stimulus) -> bool:
        match fact:
            case d.WorldObservation(world_revision=revision):
                return revision >= self._world_revision
            case d.ActivityObservation(activity_id=activity_id, activity_revision=revision):
                return (
                    activity_id != self._activity_id
                    or self._activity_revision is None
                    or revision >= self._activity_revision
                )
            case _:
                return True

    def _apply_owner_revision(self, fact: d.Stimulus) -> None:
        match fact:
            case d.WorldObservation(world_revision=revision):
                self._world_revision = revision
            case d.ActivityObservation(activity_id=activity_id, activity_revision=revision):
                self._activity_id, self._activity_revision = activity_id, revision
            case _:
                return

    def _snapshot(self) -> d.WorldInteractionSnapshot:
        return d.WorldInteractionSnapshot(
            interaction_id=self.interaction_id,
            interaction_revision=self._revision,
            user_id=None,
            pending_stimuli=self.pending_stimuli,
            now=datetime.now(timezone.utc),
            timezone=self._timezone,
            supported_outputs=frozenset(),
            world_id=self.world_id,
            world_revision=self._world_revision,
            activity_id=self._activity_id,
            activity_revision=self._activity_revision,
            planning_cycle_id=self._planning_cycle_id,
            schedule_revision=self._schedule_revision,
        )

    async def _handle(self, request: d.HandleStimulusRequest) -> None:
        sink = _WorldPlanSink(self, request)
        try:
            report = await self._agent.handle_stimulus(request, sink, context=self._context)
            self._settle(request, report, tuple(sink.ids))
        except asyncio.CancelledError:
            raise
        except Exception:
            self._logger.exception("WorldStage handle failed interaction=%s", self.interaction_id)
        finally:
            sink.closed = True

    def _settle(
        self,
        request: d.HandleStimulusRequest,
        report: d.HandlingReport,
        emitted_plan_ids: tuple[str, ...],
    ) -> None:
        pending_ids = tuple(item.stimulus_id for item in request.interaction.pending_stimuli)
        if (
            report.request_id != request.request_id
            or report.trigger_stimulus_id != request.stimulus.stimulus_id
            or report.basis_interaction_revision != request.interaction.interaction_revision
            or report.emitted_plan_ids != emitted_plan_ids
            or tuple(item for item in pending_ids if item in report.considered_pending_stimulus_ids)
            != report.considered_pending_stimulus_ids
        ):
            raise ValueError("handling report does not match request")
        for stimulus_id in report.consumed_pending_stimulus_ids:
            self._pending.pop(stimulus_id, None)
        if report.request_status is d.HandlingRequestStatus.FAILED and not report.retryable:
            self._pending.pop(request.stimulus.stimulus_id, None)
        if self._on_handling_settled is not None:
            self._on_handling_settled(request, report)

    def _handle_done(self, request_id: str, task: asyncio.Task[None]) -> None:
        self._handles.pop(request_id, None)
        self._requests.pop(request_id, None)
        if not task.cancelled() and task.exception() is not None:
            self._logger.error("WorldStage completion failed request=%s", request_id)

    def _enqueue_plan(self, plan: d.ActionPlan, token: d.CancellationToken) -> None:
        if self._state is not StageState.ONLINE:
            raise d.SinkRejectedError("stage is closed", code=d.SinkRejectionCode.SINK_CLOSED)
        try:
            self._plans.put_nowait((plan, token))
        except asyncio.QueueFull as error:
            raise d.SinkRejectedError(
                "plan queue is full",
                code=d.SinkRejectionCode.BACKPRESSURE_TIMEOUT,
            ) from error

    async def _execution_worker(self) -> None:
        while True:
            plan, handle_token = await self._plans.get()
            try:
                if handle_token.is_cancelled or self._state is not StageState.ONLINE:
                    continue
                context = d.ExecutionContext(
                    execution_id=str(uuid4()),
                    interaction_id=self.interaction_id,
                    current_interaction_revision=self._revision,
                    cancellation=d.CancellationToken(),
                )
                self._execution = context
                report = await self._agent.realize_action_plan(plan, context, self._output_sink)
                if report.status is not d.ExecutionStatus.COMPLETED:
                    self._logger.error(
                        "WorldStage realize stopped plan=%s code=%s",
                        plan.plan_id,
                        report.error_code,
                    )
                if self._on_execution_finished is not None:
                    self._on_execution_finished(plan, report)
            except asyncio.CancelledError:
                raise
            except Exception:
                self._logger.exception("WorldStage realize failed interaction=%s", self.interaction_id)
            finally:
                self._execution = None
                self._plans.task_done()

    async def wait_idle(self) -> None:
        """等待当前已接收事实的 handle 与计划执行结束。"""
        while self._handles:
            await asyncio.gather(*tuple(self._handles.values()), return_exceptions=True)
        await self._plans.join()

    async def close(self) -> None:
        """停止接收，取消在途 handle/执行并关闭长期上下文；重复调用幂等。"""
        if self._state is StageState.TERMINATED:
            return
        if self._state is StageState.TERMINATING:
            await self._closed.wait()
            return
        self._state = StageState.TERMINATING
        for request in self._requests.values():
            request.cancellation.cancel(d.CancellationReason.NO_LONGER_NEEDED)
        if self._execution is not None:
            self._execution.cancellation.cancel(d.CancellationReason.NO_LONGER_NEEDED)
        tasks = tuple(self._handles.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._worker.cancel()
        await asyncio.gather(self._worker, return_exceptions=True)
        self._requests.clear()
        self._handles.clear()
        self._pending.clear()
        while not self._plans.empty():
            self._plans.get_nowait()
            self._plans.task_done()
        await self._context.close()
        self._state = StageState.TERMINATED
        self._closed.set()
