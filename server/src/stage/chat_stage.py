"""一个用户与角色之间的刺激调度、计划执行和结束流程。"""
from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from uuid import uuid4
from zoneinfo import ZoneInfo

import src.domain.agent as d
from src.domain.stage import (
    AgentPresentationChanged, AgentPresentationState, CancelDelivery,
    StageOutput, StageState, StageTerminationResult,
)
from src.utils.logger import get_logger
from ._config import _StageConfig
from ._sinks import StimulusInputSink, _AgentOutputSink, _PlanSink

if TYPE_CHECKING:
    from src.agent.facade import Agent
    from src.adapter.websocket import WebSocketAdapter


_COORDINATION = (d.UserTyping, d.ImageSelectionOpened, d.ImageSelectionClosed,
                 d.InteractionDeadline, d.InteractionEnding)
_SUPPORTED = frozenset({d.AgentOutputKind.TEXT_FINAL, d.AgentOutputKind.AUDIO_CHUNK,
                       d.AgentOutputKind.EXPRESSION, d.AgentOutputKind.MESSAGE_END})


class ChatStage:
    """持有单个交互；handle 和 realize 各自串行，二者可以并行。"""

    def __init__(self, *, user_id: str, character_id: str, agent: Agent,
                 adapter: WebSocketAdapter, config: dict | None = None,
                 timezone_name: str = "Asia/Shanghai") -> None:
        """绑定用户、角色、agent 和共享 adapter；config 控制队列及终止等待上限。"""
        if any(not isinstance(value, str) or not value.strip() for value in (user_id, character_id)):
            raise ValueError("user_id and character_id must be nonblank")
        self._user_id, self._character_id = user_id, character_id
        self._interaction_id = str(uuid4())
        self._agent, self._adapter = agent, adapter
        self._config = _StageConfig.from_dict({} if config is None else config)
        self._timezone = ZoneInfo(timezone_name)
        self._state = StageState.OFFLINE
        self._connection_state = d.ConnectionState.DISCONNECTED
        self._revision = 0
        self._pending: dict[str, d.Stimulus] = {}
        self._inputs: deque[d.Stimulus] = deque()
        self._plans: deque[tuple[d.ActionPlan, d.CancellationToken]] = deque()
        self._request: d.HandleStimulusRequest | None = None
        self._execution: d.ExecutionContext | None = None
        self._handling: asyncio.Task[None] | None = None
        self._realizing: asyncio.Task[None] | None = None
        self._deadline: datetime | None = None
        self._waiting_revision = 0
        self._timer: asyncio.TimerHandle | None = None
        self._termination: asyncio.Task[StageTerminationResult] | None = None
        self._stimulus_sink = StimulusInputSink(self)
        self._output_sink = _AgentOutputSink(self)
        self._logger = get_logger(__name__)

    @property
    def stimulus_input_sink(self) -> StimulusInputSink:
        """返回本交互长期持有的刺激接收器。"""
        return self._stimulus_sink

    @property
    def agent_output_sink(self) -> d.AgentOutputSink:
        """返回供当前 realize 使用的唯一输出接收器。"""
        return self._output_sink

    async def connection_changed(self, state: d.ConnectionState) -> None:
        """应用连接状态；断线停止当前处理和执行，保留 pending 供重连后的刺激处理。"""
        if not isinstance(state, d.ConnectionState):
            raise TypeError("state must be ConnectionState")
        if self._state in (StageState.TERMINATING, StageState.TERMINATED):
            if state is d.ConnectionState.CONNECTED:
                raise ValueError("stage is ending")
            self._connection_state = state
            return
        if self._connection_state is state:
            return
        self._connection_state = state
        self._revision += 1
        self._state = StageState.ONLINE if state is d.ConnectionState.CONNECTED else StageState.OFFLINE
        if self._state is StageState.OFFLINE:
            await self._stop_work()

    async def terminate(self, reason: d.InteractionEndingReason) -> StageTerminationResult:
        """停止普通工作，向 Agent 发送 reason 对应的结束刺激；返回处理报告或失败说明。"""
        if not isinstance(reason, d.InteractionEndingReason):
            raise TypeError("reason must be InteractionEndingReason")
        if self._termination is None:
            self._state = StageState.TERMINATING
            self._termination = asyncio.create_task(self._terminate(reason), name="stage-terminate")
        return await asyncio.shield(self._termination)

    @property
    def interaction_id(self) -> str:
        """返回在重连期间保持不变的交互 ID。"""
        return self._interaction_id

    @property
    def user_id(self) -> str:
        """返回本交互的认证用户 ID。"""
        return self._user_id

    @property
    def character_id(self) -> str:
        """返回本交互的角色 ID。"""
        return self._character_id

    @property
    def state(self) -> StageState:
        """返回当前生命周期状态。"""
        return self._state

    def _can_accept(self, stimulus: d.Stimulus) -> bool:
        return (isinstance(stimulus, d.Stimulus) and not isinstance(stimulus, d.InteractionEnding)
                and self._state is StageState.ONLINE and stimulus.user_id == self.user_id
                and self.character_id in stimulus.target_character_ids
                and len(self._inputs) < self._config.max_stimuli
                and (isinstance(stimulus, _COORDINATION) or len(self._pending) < self._config.max_stimuli)
                and stimulus.stimulus_id not in self._pending
                and all(item.stimulus_id != stimulus.stimulus_id for item in self._inputs))

    def _receive(self, stimulus: d.Stimulus) -> bool:
        if not self._can_accept(stimulus):
            return False
        self._revision += 1
        if not isinstance(stimulus, _COORDINATION):
            self._pending[stimulus.stimulus_id] = stimulus
        self._inputs.append(stimulus)
        handle_interruptible = self._request is not None and self._agent.is_handle_interruptible(self.interaction_id)
        self._update_waiting(stimulus, handle_interruptible)
        interrupts = self._interrupts(stimulus)
        if handle_interruptible and interrupts:
            self._request.cancellation.cancel(d.CancellationReason.SUPERSEDED)
        if (self._execution is not None and interrupts
                and self._agent.is_realize_interruptible(self.interaction_id)):
            self._execution.cancellation.cancel(d.CancellationReason.SUPERSEDED)
        if self._handling is None or self._handling.done():
            self._handling = asyncio.create_task(self._handle_inputs(), name="stage-handle")
        return True

    def _interrupts(self, stimulus: d.Stimulus) -> bool:
        if isinstance(stimulus, d.UserTyping):
            return stimulus.text_length > 0
        return isinstance(stimulus, (d.TextMessage, d.ImageMessage, d.VoiceMessage,
                                     d.ImageSelectionOpened, d.ImageSelectionClosed))

    def _update_waiting(self, stimulus: d.Stimulus, extracting: bool) -> None:
        delay = None
        if isinstance(stimulus, (d.TextMessage, d.ImageMessage, d.VoiceMessage)):
            delay = self._config.response_wait
        elif isinstance(stimulus, d.UserTyping) and (self._pending or extracting):
            delay = 10.0 if stimulus.text_length > 0 else 0.0
        elif isinstance(stimulus, d.ImageSelectionOpened) and (self._pending or extracting):
            delay = 60.0
        elif isinstance(stimulus, d.ImageSelectionClosed):
            delay = self._config.response_wait if self._pending or extracting else 0.0
        if delay is None:
            return
        self._waiting_revision += 1
        # 新的补全信号使已经排队的旧期限失效，但不取消正在生成的回复。
        self._inputs = deque(item for item in self._inputs if not isinstance(item, d.InteractionDeadline))
        self._schedule(stimulus.occurred_at + timedelta(seconds=delay))

    def _snapshot(self) -> d.ChatInteractionSnapshot:
        return d.ChatInteractionSnapshot(
            interaction_id=self.interaction_id, interaction_revision=self._revision,
            user_id=self.user_id, pending_stimuli=tuple(self._pending.values()),
            now=datetime.now(timezone.utc), timezone=self._timezone, supported_outputs=_SUPPORTED,
            response_deadline=self._deadline,
            connection_state=self._connection_state,
        )

    async def _handle_inputs(self) -> None:
        while self._inputs and self._state is StageState.ONLINE:
            stimulus = self._inputs.popleft()
            if not isinstance(stimulus, _COORDINATION) and stimulus.stimulus_id not in self._pending:
                continue
            await self._handle(stimulus)

    async def _handle(self, stimulus: d.Stimulus) -> d.HandlingReport | None:
        request = d.HandleStimulusRequest(request_id=str(uuid4()), stimulus=stimulus,
                                         interaction=self._snapshot(), cancellation=d.CancellationToken())
        self._request = request
        waiting_revision = self._waiting_revision
        sink = _PlanSink(self, request)
        try:
            report = await self._agent.handle_stimulus(request, sink)
            pending_ids = tuple(item.stimulus_id for item in request.interaction.pending_stimuli)
            if (report.request_id != request.request_id or report.trigger_stimulus_id != stimulus.stimulus_id
                    or report.basis_interaction_revision != request.interaction.interaction_revision
                    or report.emitted_plan_ids != tuple(sink.ids)
                    or tuple(i for i in pending_ids if i in report.considered_pending_stimulus_ids)
                    != report.considered_pending_stimulus_ids):
                raise ValueError("handling report does not match request")
            # 报告中的真实消费事实仍有效；新到达的 pending 不在旧报告中，不能被移除。
            for stimulus_id in report.consumed_pending_stimulus_ids:
                self._pending.pop(stimulus_id, None)
            self._revision += 1
            if report.request_status is d.HandlingRequestStatus.FAILED:
                self._logger.error("Stage handle failed interaction=%s code=%s", self.interaction_id, report.error_code)
            if not self._pending:
                self._clear_timer()
                self._inputs = deque(item for item in self._inputs if not isinstance(item, d.InteractionDeadline))
            elif (not request.cancellation.is_cancelled and report.request_status is d.HandlingRequestStatus.COMPLETED
                    and self._state is StageState.ONLINE and waiting_revision == self._waiting_revision
                    and report.reconsider_at is not None):
                self._schedule(report.reconsider_at)
            return report
        except asyncio.CancelledError:
            raise
        except Exception:
            self._logger.exception("Stage handle stopped interaction=%s", self.interaction_id)
            return None
        finally:
            sink.closed = True
            self._request = None
            if self._state is StageState.ONLINE:
                self._send_control(AgentPresentationChanged(interaction_id=self.interaction_id,
                                                          state=AgentPresentationState.WAITING))

    def _enqueue_plan(self, plan: d.ActionPlan, token: d.CancellationToken) -> None:
        if self._state is not StageState.ONLINE:
            raise d.SinkRejectedError("stage is offline", code=d.SinkRejectionCode.SINK_CLOSED)
        if len(self._plans) >= self._config.max_plans:
            raise d.SinkRejectedError("plan queue is full", code=d.SinkRejectionCode.BACKPRESSURE_TIMEOUT)
        self._plans.append((plan, token))
        if self._realizing is None or self._realizing.done():
            self._realizing = asyncio.create_task(self._realize_plans(), name="stage-realize")

    async def _realize_plans(self) -> None:
        while self._plans and self._state is StageState.ONLINE:
            plan, token = self._plans.popleft()
            if token.is_cancelled:
                continue
            context = d.ExecutionContext(execution_id=str(uuid4()), interaction_id=self.interaction_id,
                                         current_interaction_revision=self._revision, cancellation=d.CancellationToken())
            self._execution = context
            cancelled = True
            try:
                report = await self._agent.realize_action_plan(plan, context, self.agent_output_sink)
                cancelled = report.status is d.ExecutionStatus.CANCELLED
                if report.status is not d.ExecutionStatus.COMPLETED:
                    self._logger.error("Stage realize stopped interaction=%s code=%s", self.interaction_id, report.error_code)
            except asyncio.CancelledError:
                raise
            except Exception:
                cancelled = False
                self._logger.exception("Stage realize failed interaction=%s", self.interaction_id)
            finally:
                if cancelled or self._output_sink.active is not None:
                    self._send_control(CancelDelivery(interaction_id=self.interaction_id, execution_id=context.execution_id))
                self._output_sink.active = None
                self._execution = None

    def _send(self, output: StageOutput) -> asyncio.Future[None]:
        return self._adapter.submit_output(output)

    def _send_control(self, output: StageOutput) -> None:
        try:
            self._send(output)
        except d.SinkRejectedError:
            self._logger.debug("Stage control unavailable interaction=%s", self.interaction_id)

    def _clear_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._deadline = None

    def _schedule(self, deadline: datetime | None) -> None:
        self._clear_timer()
        if deadline is None or not self._pending:
            return
        self._deadline = deadline
        delay = max(0.0, (deadline - datetime.now(timezone.utc)).total_seconds())
        self._timer = asyncio.get_running_loop().call_later(delay, self._deadline_due)

    def _stage_stimulus_fields(self) -> dict:
        return dict(stimulus_id=str(uuid4()), schema_version=1, occurred_at=datetime.now(timezone.utc),
                    source=d.StimulusSource.STAGE, target_character_ids=(self.character_id,), user_id=self.user_id, ephemeral=True)

    def _deadline_due(self) -> None:
        self._timer = None
        self._receive(d.InteractionDeadline(**self._stage_stimulus_fields()))

    async def _stop_work(self) -> None:
        self._clear_timer()
        self._inputs.clear()
        self._plans.clear()
        for context in (self._request, self._execution):
            if context is not None:
                context.cancellation.cancel(d.CancellationReason.NO_LONGER_NEEDED)
        tasks = [task for task in (self._handling, self._realizing) if task is not None and not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _terminate(self, reason: d.InteractionEndingReason) -> StageTerminationResult:
        report, error = None, None
        try:
            await self._stop_work()
            report = await asyncio.wait_for(
                self._handle(d.InteractionEnding(reason=reason, **self._stage_stimulus_fields())),
                timeout=self._config.termination_timeout,
            )
            if report is None or report.request_status is not d.HandlingRequestStatus.COMPLETED:
                error = "interaction ending handler failed"
        except asyncio.TimeoutError:
            error = "interaction ending timed out"
            self._logger.error("Stage termination timed out interaction=%s", self.interaction_id)
        finally:
            self._pending.clear()
            self._state = StageState.TERMINATED
        return StageTerminationResult(report=report, error=error)
