"""一个用户与角色之间的刺激调度、计划执行和结束流程。"""

from __future__ import annotations

import asyncio
import random
import time
from collections import deque
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from uuid import uuid4
from zoneinfo import ZoneInfo

import src.domain.agent as d
from src.agent.context import ContextFactory, InteractionContext
from src.domain.stage import (
    AgentPresentationChanged,
    AgentPresentationState,
    CancelDelivery,
    StageOutput,
    StageState,
    StageTerminationResult,
)
from src.utils.logger import get_logger

from ._config import _StageConfig
from ._models import _InputStatus, _PendingInput, _ReplyAttempt
from ._sinks import StimulusInputSink, _AgentOutputSink, _PlanSink
from .due_events import DueEvent, DueEventProvider

if TYPE_CHECKING:
    from src.adapter.websocket import WebSocketAdapter
    from src.agent.facade import Agent


_CONTENT = (d.TextMessage, d.ImageMessage, d.VoiceMessage)

_COORDINATION = (
    d.UserTyping,
    d.ImageSelectionOpened,
    d.ImageSelectionClosed,
    d.InteractionDeadline,
    d.InteractionEnding,
)
_SUPPORTED = frozenset(
    {
        d.AgentOutputKind.TEXT_FINAL,
        d.AgentOutputKind.AUDIO_CHUNK,
        d.AgentOutputKind.EXPRESSION,
        d.AgentOutputKind.MESSAGE_END,
    }
)


class ChatStage:
    """持有交互上下文；并行预处理、有序聚合回复，串行执行计划并管理取消与结束。"""

    def __init__(
        self,
        *,
        user_id: str,
        character_id: str,
        agent: Agent,
        adapter: WebSocketAdapter,
        context: InteractionContext,
        config: dict | None = None,
        timezone_name: str = "Asia/Shanghai",
        due_event_provider: DueEventProvider | None = None,
    ) -> None:
        """接管 context 并绑定用户、角色与协作者；config 控制等待秒数、容量和终止期限。"""
        if any(not isinstance(value, str) or not value.strip() for value in (user_id, character_id)):
            raise ValueError("user_id and character_id must be nonblank")
        self._user_id, self._character_id = user_id, character_id
        if context.identity.user_id != user_id or context.identity.character_id != character_id:
            raise ValueError("context identity does not match stage")
        self._context = context
        self._interaction_id = context.identity.interaction_id
        self._agent, self._adapter = agent, adapter
        self._due_event_provider = due_event_provider
        self._config = _StageConfig.from_dict({} if config is None else config)
        self._timezone = ZoneInfo(timezone_name)
        self._state = StageState.OFFLINE
        self._connection_state = d.ConnectionState.DISCONNECTED
        self._revision = 0
        self._pending: dict[str, _PendingInput] = {}
        self._attempts: dict[str, _ReplyAttempt] = {}
        self._reply: _ReplyAttempt | None = None
        self._executing_plan: d.ActionPlan | None = None
        self._scheduling = False
        self._wait_until: datetime | None = None
        self._wait_immediate = False
        self._requests: dict[str, d.HandleStimulusRequest] = {}
        self._handles: dict[str, asyncio.Task] = {}
        self._thinking: set[str] = set()
        self._plans: deque[tuple[d.ActionPlan, d.CancellationToken]] = deque()
        self._execution: d.ExecutionContext | None = None
        self._realizing: asyncio.Task[None] | None = None
        self._deadline: datetime | None = None
        self._schedule_revision = 0
        self._timer: asyncio.TimerHandle | None = None
        self._first_login_timer: asyncio.TimerHandle | None = None
        self._first_login_pending = False
        self._login_reminder_timer: asyncio.TimerHandle | None = None
        self._login_reminder_dispatch: asyncio.Task[bool] | None = None
        self._login_reminder_pending = False
        self._last_activity_at = datetime.now(timezone.utc)
        self._proactive_claims: dict[str, tuple[DueEvent, ...]] = {}
        self._proactive_expected_plans: dict[str, set[str]] = {}
        self._proactive_plan_results: dict[str, dict[str, bool]] = {}
        self._termination: asyncio.Task[StageTerminationResult] | None = None
        self._stimulus_sink = StimulusInputSink(self)
        self._output_sink = _AgentOutputSink(self)
        self._logger = get_logger(__name__)

    @classmethod
    async def create(
        cls,
        *,
        user_id: str,
        character_id: str,
        agent: Agent,
        adapter: WebSocketAdapter,
        context_factory: ContextFactory,
        config: dict | None = None,
        timezone_name: str = "Asia/Shanghai",
        due_event_provider: DueEventProvider | None = None,
    ) -> ChatStage:
        """通过 context_factory 加载新上下文，返回持有它的 Stage；构造失败时关闭上下文。"""
        context = await context_factory.create(str(uuid4()), user_id=user_id)
        try:
            return cls(
                user_id=user_id,
                character_id=character_id,
                agent=agent,
                adapter=adapter,
                context=context,
                config=config,
                timezone_name=timezone_name,
                due_event_provider=due_event_provider,
            )
        except BaseException:
            await context.close()
            raise

    @property
    def context(self) -> InteractionContext:
        """返回本交互独占持有的上下文；断线保留期间复用，最终结束时关闭。"""
        return self._context

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
        self._last_activity_at = datetime.now(timezone.utc)
        self._revision += 1
        self._state = StageState.ONLINE if state is d.ConnectionState.CONNECTED else StageState.OFFLINE
        if self._state is StageState.OFFLINE:
            await self._stop_work()
        elif self._first_login_pending:
            self._schedule_first_login()
        elif self._login_reminder_pending:
            self._schedule_login_reminders()

    def schedule_first_login(self) -> None:
        """记录首次登录，并在 Stage 已上线后从当前时刻开始同步窗口计时。"""
        if self._state in (StageState.TERMINATING, StageState.TERMINATED):
            raise ValueError("stage is ending")
        self._first_login_pending = True
        if self._state is StageState.ONLINE:
            self._schedule_first_login()

    def schedule_login_reminders(self) -> None:
        """记录当天首次普通登录，并在 Stage 上线后合并可 claim 的到期提醒。"""
        if self._state in (StageState.TERMINATING, StageState.TERMINATED):
            raise ValueError("stage is ending")
        self._login_reminder_pending = True
        if self._state is StageState.ONLINE:
            self._schedule_login_reminders()

    async def dispatch_due_events(self, *, merge_all: bool) -> bool:
        """在流空闲时筛选、claim 并向 Agent 投递一个或合并后的到期事实。"""
        if self._due_event_provider is None or not self._can_dispatch_proactive(
            require_idle=not merge_all,
        ):
            return False
        now = datetime.now(timezone.utc)
        candidates = tuple(
            event
            for event in self._due_event_provider.list_due(
                character_id=self.character_id,
                user_id=self.user_id,
                now=now,
            )
            if self._supports_due_event(event)
        )
        selected = candidates if merge_all else ((random.choice(candidates),) if candidates else ())
        claimed = []
        for event in selected:
            if self._due_event_provider.claim(
                event.event_id,
                user_id=self.user_id,
                character_id=self.character_id,
                trigger_key=event.trigger_key,
            ):
                claimed.append(event)
        if not claimed:
            return False
        stimulus = d.ProactivePromptDue(
            **self._stage_stimulus_fields(),
            reason=d.ProactiveReason(value="+".join(event.reason for event in claimed)),
            due_at=min(event.due_at for event in claimed),
            dedup_key="|".join(
                f"{event.event_id}:{self.user_id}:{self.character_id}:{event.trigger_key}" for event in claimed
            ),
            fact_refs=tuple(d.EvidenceRef(evidence_id=event.event_id) for event in claimed),
        )
        request = self._make_request(stimulus)
        self._proactive_claims[request.request_id] = tuple(claimed)
        self._proactive_plan_results[request.request_id] = {}
        self._last_activity_at = now
        self._launch_handle(request, self._on_proactive_handled)
        return True

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
        return (
            isinstance(stimulus, d.Stimulus)
            and not isinstance(stimulus, (d.InteractionEnding, d.InteractionDeadline))
            and self._state is StageState.ONLINE
            and stimulus.user_id == self.user_id
            and self.character_id in stimulus.target_character_ids
            and len(self._handles) < self._config.max_stimuli
            and (isinstance(stimulus, _COORDINATION) or len(self._pending) < self._config.max_stimuli)
            and stimulus.stimulus_id not in self._pending
            and all(item.stimulus.stimulus_id != stimulus.stimulus_id for item in self._requests.values())
        )

    def _receive(self, stimulus: d.Stimulus) -> bool:
        if not self._can_accept(stimulus):
            return False
        self._on_raw_stimulus(stimulus)
        return True

    def _on_raw_stimulus(self, stimulus: d.Stimulus) -> None:
        """接收原始刺激，更新等待策略并启动独立预处理。"""
        self._revision += 1
        self._last_activity_at = datetime.now(timezone.utc)
        if isinstance(stimulus, _CONTENT):
            self._cancel_reply_attempts()
            self._pending[stimulus.stimulus_id] = _PendingInput(stimulus, self._revision)
            self._wait_until, self._wait_immediate = None, False
            self._scheduling = True
            self._invalidate_deadline()
        elif isinstance(stimulus, (d.UserTyping, d.ImageSelectionOpened, d.ImageSelectionClosed)):
            if self._pending:
                delay = self._config.response_wait
                if isinstance(stimulus, d.UserTyping):
                    delay = self._config.typing_wait if stimulus.text_length else 0
                elif isinstance(stimulus, d.ImageSelectionOpened):
                    delay = self._config.image_selection_wait
                self._wait_immediate = delay == 0
                self._wait_until = datetime.now(timezone.utc) + timedelta(seconds=delay)
                self._scheduling = True
                self._invalidate_deadline()
        request = self._make_request(stimulus, (stimulus,) if not isinstance(stimulus, _COORDINATION) else ())
        self._launch_handle(request, self._on_preprocessing_finished)
        self._refresh_deadline()

    def _make_request(
        self,
        stimulus: d.Stimulus,
        pending: tuple[d.Stimulus, ...] = (),
        prepared: tuple[d.PreprocessedInput, ...] = (),
        purpose: d.HandlePurpose = d.HandlePurpose.PROCESS,
    ) -> d.HandleStimulusRequest:
        return d.HandleStimulusRequest(
            request_id=str(uuid4()),
            stimulus=stimulus,
            interaction=replace(self._snapshot(), pending_stimuli=pending),
            cancellation=d.CancellationToken(),
            prepared_inputs=prepared,
            purpose=purpose,
        )

    def _launch_handle(
        self,
        request: d.HandleStimulusRequest,
        completed: Callable[[d.HandleStimulusRequest, d.HandlingReport | None], None],
    ) -> None:
        self._requests[request.request_id] = request

        async def run() -> None:
            report = await self._handle(request)
            if self._state is StageState.ONLINE and not request.cancellation.is_cancelled:
                completed(request, report)

        task = asyncio.create_task(run(), name="stage-handle")
        self._handles[request.request_id] = task
        task.add_done_callback(lambda finished: self._handle_done(request.request_id, finished))

    def _handle_done(self, request_id: str, task: asyncio.Task[None]) -> None:
        if not task.cancelled() and task.exception() is not None:
            self._logger.error("Stage completion failed request=%s", request_id)
        self._handles.pop(request_id, None)
        self._requests.pop(request_id, None)
        if task.cancelled() or task.exception() is not None:
            self._release_proactive_claims(request_id)
        if self._reply is not None and self._reply.request.request_id == request_id:
            self._reply = None
        self._refresh_deadline()

    def _failed_report(self, request: d.HandleStimulusRequest) -> d.HandlingReport:
        ids = tuple(s.stimulus_id for s in request.interaction.pending_stimuli)
        return d.HandlingReport(
            request_id=request.request_id,
            trigger_stimulus_id=request.stimulus.stimulus_id,
            basis_interaction_revision=request.interaction.interaction_revision,
            request_status=d.HandlingRequestStatus.FAILED,
            considered_pending_stimulus_ids=ids,
            consumed_pending_stimulus_ids=(),
            retained_pending_stimulus_ids=ids,
            emitted_plan_ids=(),
            error_code=d.HandlingErrorCode.INTERNAL_ERROR,
            retryable=False,
        )

    def _on_preprocessing_finished(self, request: d.HandleStimulusRequest, report: d.HandlingReport | None) -> None:
        """按触发身份保存预处理结果，全部就绪后安排回复。"""
        entry = self._pending.get(request.stimulus.stimulus_id)
        if entry is None:
            return
        if (
            report is None
            or report.request_status is not d.HandlingRequestStatus.COMPLETED
            or report.preprocessed_input is None
        ):
            self._logger.error("Stage preprocessing failed stimulus=%s", entry.stimulus.stimulus_id)
            del self._pending[entry.stimulus.stimulus_id]
        else:
            entry.prepared = report.preprocessed_input
            entry.ready_at = datetime.now(timezone.utc)
            entry.status = _InputStatus.READY
        self._refresh_deadline()

    def _refresh_deadline(self) -> None:
        if self._state is not StageState.ONLINE or not self._scheduling:
            return
        if not self._pending:
            self._invalidate_deadline()
            self._scheduling = False
            return
        if self._reply is not None or any(e.status is not _InputStatus.READY for e in self._pending.values()):
            return
        ready_at = max(e.ready_at for e in self._pending.values())
        deadline = ready_at if self._wait_immediate else ready_at + timedelta(seconds=self._config.response_wait)
        if self._wait_until is not None:
            deadline = max(deadline, self._wait_until)
        if deadline != self._deadline:
            self._schedule_revision += 1
            self._schedule(deadline)

    def _cancel_reply_attempts(self) -> None:
        for attempt in tuple(self._attempts.values()):
            attempt.interrupted = True
            attempt.request.cancellation.cancel(d.CancellationReason.SUPERSEDED)
            task = self._handles.get(attempt.request.request_id)
            if task is not None and not task.done():
                task.cancel()
            for sid in attempt.input_ids:
                if sid in self._pending and self._pending[sid].status is _InputStatus.REPLYING:
                    self._pending[sid].status = _InputStatus.READY
            self._plans = deque(
                (plan, token) for plan, token in self._plans if plan.origin_request_id != attempt.request.request_id
            )
            attempt.remaining_plans.intersection_update(
                {self._executing_plan.plan_id} if self._executing_plan is not None else set()
            )
            if (
                self._executing_plan is not None
                and self._executing_plan.origin_request_id == attempt.request.request_id
            ):
                self._execution.cancellation.cancel(d.CancellationReason.SUPERSEDED)
                self._send_control(
                    CancelDelivery(interaction_id=self.interaction_id, execution_id=self._execution.execution_id)
                )
                self._realizing.cancel()
            if not attempt.remaining_plans:
                self._attempts.pop(attempt.request.request_id, None)

    def _on_deadline(self, revision: int) -> None:
        """验证计时修订，冻结已准备输入并启动整批回复。"""
        if revision != self._schedule_revision or self._state is not StageState.ONLINE:
            return
        self._timer = None
        self._deadline = None
        self._schedule_revision += 1
        if (
            self._reply is not None
            or not self._pending
            or any(e.status is not _InputStatus.READY for e in self._pending.values())
        ):
            return
        if len(self._handles) >= self._config.max_stimuli:
            self._logger.error("Stage reply capacity exceeded interaction=%s", self.interaction_id)
            self._scheduling = False
            return
        entries = tuple(self._pending.values())
        request = self._make_request(
            d.InteractionDeadline(**self._stage_stimulus_fields()),
            tuple(e.stimulus for e in entries),
            tuple(e.prepared for e in entries),
        )
        for entry in entries:
            entry.status = _InputStatus.REPLYING
        self._reply = _ReplyAttempt(request, tuple(e.stimulus.stimulus_id for e in entries))
        self._attempts[request.request_id] = self._reply
        self._scheduling = False
        self._launch_handle(request, self._on_reply_finished)

    def _on_reply_finished(self, request: d.HandleStimulusRequest, report: d.HandlingReport | None) -> None:
        """结算本次回复明确消费的输入，保留尚需回复的部分。"""
        attempt = self._attempts.get(request.request_id)
        if attempt is None or attempt.interrupted:
            return
        attempt.report = report if report is not None else self._failed_report(request)
        success = report is not None and report.request_status is d.HandlingRequestStatus.COMPLETED
        consumed = report.consumed_pending_stimulus_ids if report is not None else ()
        for sid in attempt.input_ids:
            if sid in consumed:
                self._pending.pop(sid, None)
                self.context.recalled_memory.remove_by_stimulus_id(sid)
            elif sid in self._pending:
                self._pending[sid].status = _InputStatus.READY
                self._pending[sid].ready_at = datetime.now(timezone.utc)
        self._reply = None
        self._scheduling = success and bool(self._pending)
        self._finish_attempt(attempt)
        self._refresh_deadline()

    def _finish_attempt(self, attempt: _ReplyAttempt) -> None:
        if attempt.remaining_plans or attempt.report is None:
            return
        self._attempts.pop(attempt.request.request_id, None)
        if attempt.interrupted or attempt.report.request_status is not d.HandlingRequestStatus.COMPLETED:
            return
        self.context.recalled_memory.remove_by_stimulus_id(attempt.request.stimulus.stimulus_id)
        if self._state is StageState.ONLINE and len(self._handles) < self._config.max_stimuli:
            consumed = set(attempt.report.consumed_pending_stimulus_ids)
            request = self._make_request(
                attempt.request.stimulus,
                tuple(s for s in attempt.request.interaction.pending_stimuli if s.stimulus_id in consumed),
                tuple(p for p in attempt.request.prepared_inputs if p.stimulus_id in consumed),
                d.HandlePurpose.REFLECT,
            )
            self._launch_handle(request, lambda request, report: None)

    def _on_execution_finished(self, plan: d.ActionPlan, report: d.ExecutionReport | None) -> None:
        """登记计划已经结束，推进所属回复尝试的清理和维护。"""
        attempt = self._attempts.get(plan.origin_request_id)
        if attempt is not None:
            attempt.remaining_plans.discard(plan.plan_id)
            if attempt.interrupted and not attempt.remaining_plans:
                self._attempts.pop(plan.origin_request_id, None)
            else:
                self._finish_attempt(attempt)
        request_id = plan.origin_request_id
        if request_id in self._proactive_claims:
            succeeded = report is not None and report.status is d.ExecutionStatus.COMPLETED
            self._proactive_plan_results[request_id][plan.plan_id] = succeeded
            self._finish_proactive_claim(request_id)

    def _snapshot(self) -> d.ChatInteractionSnapshot:
        return d.ChatInteractionSnapshot(
            interaction_id=self.interaction_id,
            interaction_revision=self._revision,
            user_id=self.user_id,
            pending_stimuli=tuple(e.stimulus for e in self._pending.values()),
            now=datetime.now(timezone.utc),
            timezone=self._timezone,
            supported_outputs=_SUPPORTED,
            response_deadline=self._deadline,
            connection_state=self._connection_state,
        )

    async def _handle(self, request: d.HandleStimulusRequest) -> d.HandlingReport | None:
        # 每次调用只提交报告；状态结算由相应的完成事件处理方法执行。
        sink = _PlanSink(self, request)
        try:
            report = await self._agent.handle_stimulus(request, sink, context=self.context)
            pending_ids = tuple(item.stimulus_id for item in request.interaction.pending_stimuli)
            if (
                report.request_id != request.request_id
                or report.trigger_stimulus_id != request.stimulus.stimulus_id
                or report.basis_interaction_revision != request.interaction.interaction_revision
                or report.emitted_plan_ids != tuple(sink.ids)
                or tuple(i for i in pending_ids if i in report.considered_pending_stimulus_ids)
                != report.considered_pending_stimulus_ids
            ):
                raise ValueError("handling report does not match request")
            if (
                report.preprocessed_input is not None
                and report.preprocessed_input.stimulus_id != request.stimulus.stimulus_id
            ):
                raise ValueError("preprocessing result identity mismatch")
            if report.request_status is d.HandlingRequestStatus.FAILED:
                self._logger.error("Stage handle failed interaction=%s code=%s", self.interaction_id, report.error_code)
            return report
        except asyncio.CancelledError:
            raise
        except Exception:
            self._logger.exception("Stage handle stopped interaction=%s", self.interaction_id)
            return None
        finally:
            sink.closed = True
            self._requests.pop(request.request_id, None)
            was_thinking = request.request_id in self._thinking
            self._thinking.discard(request.request_id)
            if was_thinking and not self._thinking and self._state is StageState.ONLINE:
                self._send_control(
                    AgentPresentationChanged(interaction_id=self.interaction_id, state=AgentPresentationState.WAITING)
                )

    def _enqueue_plan(self, plan: d.ActionPlan, token: d.CancellationToken) -> None:
        if self._state is not StageState.ONLINE:
            raise d.SinkRejectedError("stage is offline", code=d.SinkRejectionCode.SINK_CLOSED)
        if len(self._plans) >= self._config.max_plans:
            raise d.SinkRejectedError("plan queue is full", code=d.SinkRejectionCode.BACKPRESSURE_TIMEOUT)
        self._plans.append((plan, token))
        attempt = self._attempts.get(plan.origin_request_id)
        if attempt is not None:
            attempt.remaining_plans.add(plan.plan_id)
        if self._realizing is None or self._realizing.done():
            self._realizing = asyncio.create_task(self._realize_plans(), name="stage-realize")
            self._realizing.add_done_callback(lambda _: self._resume_execution())

    def _resume_execution(self) -> None:
        if self._plans and self._state is StageState.ONLINE and (self._realizing is None or self._realizing.done()):
            self._realizing = asyncio.create_task(self._realize_plans(), name="stage-realize")
            self._realizing.add_done_callback(lambda _: self._resume_execution())

    async def _realize_plans(self) -> None:
        while self._plans and self._state is StageState.ONLINE:
            plan, token = self._plans.popleft()
            if token.is_cancelled:
                continue
            context = d.ExecutionContext(
                execution_id=str(uuid4()),
                interaction_id=self.interaction_id,
                current_interaction_revision=self._revision,
                cancellation=d.CancellationToken(),
            )
            self._execution = context
            self._executing_plan = plan
            report = None
            cancelled = True
            try:
                report = await self._agent.realize_action_plan(plan, context, self.agent_output_sink)
                cancelled = report.status is d.ExecutionStatus.CANCELLED
                if report.status is not d.ExecutionStatus.COMPLETED:
                    self._logger.error(
                        "Stage realize stopped interaction=%s code=%s", self.interaction_id, report.error_code
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                cancelled = False
                self._logger.exception("Stage realize failed interaction=%s", self.interaction_id)
            finally:
                if cancelled or self._output_sink.active is not None:
                    self._send_control(
                        CancelDelivery(interaction_id=self.interaction_id, execution_id=context.execution_id)
                    )
                self._output_sink.active = None
                self._execution = None
                self._executing_plan = None
                self._on_execution_finished(plan, report)

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
        if deadline is None:
            return
        self._deadline = deadline
        delay = max(0.0, (deadline - datetime.now(timezone.utc)).total_seconds())
        self._timer = asyncio.get_running_loop().call_later(delay, self._on_deadline, self._schedule_revision)

    def _schedule_first_login(self) -> None:
        if self._first_login_timer is not None:
            return
        # asyncio 允许定时器最多提前一个单调时钟分辨率触发；Windows 常为 15.625ms。
        # 欢迎等待是“不早于”的产品语义，因此补偿该分辨率，避免 40ms 配置在约 31ms 时触发。
        minimum_delay = self._config.first_login_wait + time.get_clock_info("monotonic").resolution
        self._first_login_timer = asyncio.get_running_loop().call_later(
            minimum_delay,
            self._on_first_login_due,
        )

    def _on_first_login_due(self) -> None:
        self._first_login_timer = None
        if not self._first_login_pending or self._state is not StageState.ONLINE:
            return
        if len(self._handles) >= self._config.max_stimuli:
            self._schedule_first_login()
            return
        self._first_login_pending = False
        stimulus = d.ProactivePromptDue(
            **self._stage_stimulus_fields(),
            reason=d.ProactiveReason(value="first_login"),
            due_at=datetime.now(timezone.utc),
            dedup_key=f"first-login:{self.user_id}:{self.character_id}",
            fact_refs=(),
        )
        self._launch_handle(self._make_request(stimulus), lambda request, report: None)

    def _schedule_login_reminders(self) -> None:
        if self._login_reminder_timer is not None:
            return
        minimum_delay = self._config.login_reminder_wait + time.get_clock_info("monotonic").resolution
        self._login_reminder_timer = asyncio.get_running_loop().call_later(
            minimum_delay,
            self._on_login_reminders_due,
        )

    def _on_login_reminders_due(self) -> None:
        self._login_reminder_timer = None
        if not self._login_reminder_pending or self._state is not StageState.ONLINE:
            return
        if not self._can_dispatch_proactive(require_idle=False):
            self._schedule_login_reminders()
            return
        self._login_reminder_pending = False
        self._login_reminder_dispatch = asyncio.create_task(
            self.dispatch_due_events(merge_all=True),
            name="stage-login-reminders",
        )
        self._login_reminder_dispatch.add_done_callback(
            lambda _: setattr(self, "_login_reminder_dispatch", None),
        )

    def _can_dispatch_proactive(self, *, require_idle: bool = True) -> bool:
        if self._state is not StageState.ONLINE:
            return False
        busy = bool(
            self._handles
            or self._pending
            or self._plans
            or self._executing_plan
            or (self._realizing is not None and not self._realizing.done())
        )
        if busy:
            return False
        idle_seconds = (datetime.now(timezone.utc) - self._last_activity_at).total_seconds()
        return not require_idle or idle_seconds >= self._config.proactive_idle_seconds

    def _supports_due_event(self, event: DueEvent) -> bool:
        supported = {"holiday", "travel", "new_song", "birthday", "anniversary"}
        return (
            event.reason in supported
            and event.character_id == self.character_id
            and (not event.is_personal or event.target_user_id == self.user_id)
            and not event.is_notified
        )

    def _on_proactive_handled(
        self,
        request: d.HandleStimulusRequest,
        report: d.HandlingReport | None,
    ) -> None:
        if report is None or report.request_status is not d.HandlingRequestStatus.COMPLETED:
            self._release_proactive_claims(request.request_id)
            return
        self._proactive_expected_plans[request.request_id] = set(report.emitted_plan_ids)
        if not report.emitted_plan_ids:
            self._release_proactive_claims(request.request_id)
            return
        self._finish_proactive_claim(request.request_id)

    def _finish_proactive_claim(self, request_id: str) -> None:
        expected = self._proactive_expected_plans.get(request_id)
        results = self._proactive_plan_results.get(request_id, {})
        if expected is None or not expected.issubset(results):
            return
        if not all(results[plan_id] for plan_id in expected):
            self._release_proactive_claims(request_id)
            return
        self._proactive_claims.pop(request_id, None)
        self._proactive_expected_plans.pop(request_id, None)
        self._proactive_plan_results.pop(request_id, None)

    def _release_proactive_claims(self, request_id: str) -> None:
        claims = self._proactive_claims.pop(request_id, ())
        self._proactive_expected_plans.pop(request_id, None)
        self._proactive_plan_results.pop(request_id, None)
        if self._due_event_provider is None:
            return
        for event in claims:
            self._due_event_provider.release(
                event.event_id,
                user_id=self.user_id,
                character_id=self.character_id,
                trigger_key=event.trigger_key,
            )

    def _stage_stimulus_fields(self) -> dict:
        return {
            "stimulus_id": str(uuid4()),
            "schema_version": 1,
            "occurred_at": datetime.now(timezone.utc),
            "source": d.StimulusSource.STAGE,
            "target_character_ids": (self.character_id,),
            "user_id": self.user_id,
            "ephemeral": True,
        }

    def _invalidate_deadline(self) -> None:
        self._schedule_revision += 1
        self._clear_timer()

    async def _stop_work(self) -> None:
        self._scheduling = False
        self._invalidate_deadline()
        if self._first_login_timer is not None:
            self._first_login_timer.cancel()
            self._first_login_timer = None
        if self._login_reminder_timer is not None:
            self._login_reminder_timer.cancel()
            self._login_reminder_timer = None
        self._plans.clear()
        for context in (*self._requests.values(), self._execution):
            if context is not None:
                context.cancellation.cancel(d.CancellationReason.NO_LONGER_NEEDED)
        tasks = [
            task
            for task in (*self._handles.values(), self._realizing, self._login_reminder_dispatch)
            if task is not None and not task.done()
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for request_id in tuple(self._proactive_claims):
            self._release_proactive_claims(request_id)
        self._requests.clear()
        self._handles.clear()
        self._thinking.clear()
        self._reply = None
        self._attempts.clear()
        for entry in self._pending.values():
            if entry.status is _InputStatus.REPLYING:
                entry.status = _InputStatus.READY
        self._pending = {sid: e for sid, e in self._pending.items() if e.status is _InputStatus.READY}

    async def _terminate(self, reason: d.InteractionEndingReason) -> StageTerminationResult:
        report, error = None, None
        try:
            await self._stop_work()
            report = await asyncio.wait_for(
                self._handle(
                    self._make_request(
                        d.InteractionEnding(reason=reason, **self._stage_stimulus_fields()),
                        tuple(e.stimulus for e in self._pending.values()),
                        tuple(e.prepared for e in self._pending.values()),
                    )
                ),
                timeout=self._config.termination_timeout,
            )
            if report is None or report.request_status is not d.HandlingRequestStatus.COMPLETED:
                error = "interaction ending handler failed"
        except asyncio.TimeoutError:
            error = "interaction ending timed out"
            self._logger.error("Stage termination timed out interaction=%s", self.interaction_id)
        finally:
            await self._context.close()
            self._pending.clear()
            self._state = StageState.TERMINATED
        return StageTerminationResult(report=report, error=error)
