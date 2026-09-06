"""角色门面：校验、内部路由、单次交付结算及在途调用所有权。"""

import asyncio
from traceback import walk_tb

import src.domain.agent as d
from src.agent.processing.execution import Execution
from src.agent.handlers.action.router import ActionHandler, ActionRouter
from src.agent.handlers.stimulus.router import StimulusHandler, StimulusRouter
from src.agent.processing.plan_emitter import handling_error
from src.agent.processing.handling import Handling
from src.utils.logger import get_logger


class Agent:
    """角色的两接口业务门面，内部委托已注册处理器并结算接收与效果事实。

    AgentRuntime 装配角色私有路由并管理接受状态；生产注册表为空。
    每次调用独立处理；失败记录日志并结束，接收器只属于本次调用。
    """

    __slots__ = ("_character_id", "_accepting", "_logger", "_stimulus_router", "_action_router", "_inflight")

    def __init__(
        self,
        *,
        character_id: str,
        stimulus_router: StimulusRouter[StimulusHandler] | None = None,
        action_router: ActionRouter[ActionHandler] | None = None
    ) -> None:
        """绑定角色和内部路由；空白角色抛 ValueError，省略路由使用空注册表。"""
        if not isinstance(character_id, str) or not character_id.strip():
            raise ValueError("Agent requires a nonblank character_id")
        self._character_id = character_id
        self._accepting = True
        self._logger = get_logger(__name__)
        self._stimulus_router = stimulus_router if stimulus_router is not None else StimulusRouter(())
        self._action_router = action_router if action_router is not None else ActionRouter(())
        self._inflight: set[asyncio.Future] = set()

    async def handle_stimulus(self, request: d.HandleStimulusRequest, plan_sink: d.ActionPlanSink) -> d.HandlingReport:
        """校验刺激并调用处理器，按顺序交付计划，返回本次处理报告。

        失败后记录日志并停止交付，不保存或恢复请求。类型错误抛 TypeError；
        协作取消返回取消报告，任务取消等待处理器清理后传播 CancelledError。
        """
        if not isinstance(request, d.HandleStimulusRequest):
            raise TypeError("request must be HandleStimulusRequest")
        self._check_sink(plan_sink)
        stimuli = (request.stimulus, *request.interaction.pending_stimuli)
        error = None
        status = d.HandlingRequestStatus.FAILED
        if any(self._character_id not in item.target_character_ids for item in stimuli):
            error = d.HandlingErrorCode.CONTRACT_SNAPSHOT_MISMATCH
        elif not self._accepting:
            error = d.HandlingErrorCode.DEPENDENCY_UNAVAILABLE
        if error is not None:
            report = self._handling_failure(request, status, error)
            self._record(request.request_id, request.interaction.interaction_id, status, error)
            return report
        # 没有error的路径：
        completion = self._begin_call()
        report = None
        try:
            report = await Handling(self, request, plan_sink).run()
            return report
        finally:  # 所有路径都会走finally
            try:
                if report is not None:
                    self._record(request.request_id, request.interaction.interaction_id, report.request_status, report.error_code)
            finally:
                self._end_call(completion)

    async def realize_action_plan(
        self, plan: d.ActionPlan, context: d.ExecutionContext, output_sink: d.AgentOutputSink
    ) -> d.ExecutionReport:
        """校验计划及上下文，预检全部处理器后按顺序执行行动和交付输出。

        失败后保留已完成结果，停止后续行动并返回报告，不保存或恢复执行。
        类型错误抛 TypeError；任务取消等待处理器清理后传播 CancelledError。
        """
        if not isinstance(plan, d.ActionPlan) or not isinstance(context, d.ExecutionContext):
            raise TypeError("plan and context must be domain objects")
        self._check_sink(output_sink)
        error = None
        if plan.target_character_id != self._character_id or plan.interaction_id != context.interaction_id:
            error = d.ExecutionErrorCode.CONTRACT_MISMATCH
        elif not self._accepting:
            error = d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE
        if error is not None:
            report = self._execution_report(plan, context, d.ExecutionStatus.FAILED, error, [], False, False)
            self._record(context.execution_id, context.interaction_id, report.status, report.error_code)
            return report

        completion = self._begin_call()
        try:
            report = await Execution(self, plan, context, output_sink).run()
        except asyncio.CancelledError:
            self._record(
                context.execution_id, context.interaction_id, d.ExecutionStatus.CANCELLED, d.ExecutionErrorCode.CANCELLED
            )
            raise
        finally:
            self._end_call(completion)
        self._record(context.execution_id, context.interaction_id, report.status, report.error_code)
        return report

    def _stop_accepting(self) -> None:
        self._accepting = False

    def _begin_call(self):
        completion = asyncio.get_running_loop().create_future()
        self._inflight.add(completion)
        return completion

    def _end_call(self, completion):
        completion.set_result(None)
        self._inflight.discard(completion)

    @staticmethod
    def _handling_failure(request: d.HandleStimulusRequest, status: d.HandlingRequestStatus, error: d.HandlingErrorCode, emitted: tuple[str, ...] = (), retryable: bool = False) -> d.HandlingReport:
        pending = tuple(item.stimulus_id for item in request.interaction.pending_stimuli)
        return d.HandlingReport(
            request_id=request.request_id,
            request_status=status,
            trigger_stimulus_id=request.stimulus.stimulus_id,
            basis_interaction_revision=request.interaction.interaction_revision,
            considered_pending_stimulus_ids=pending,
            consumed_pending_stimulus_ids=(),
            retained_pending_stimulus_ids=pending,
            emitted_plan_ids=tuple(emitted),
            reconsider_at=None,
            error_code=error,
            retryable=retryable,
        )

    @staticmethod
    def _action_result(action, status=d.ActionExecutionStatus.NOT_STARTED, error=None):
        return d.ActionResult(
            action_id=action.action_id, status=status, error_code=error, irreversible_effect_committed=False, effect_ref=None
        )

    def _execution_report(self, plan, context, status, error, results, started, retryable):
        remaining = tuple(self._action_result(action) for action in plan.actions[len(results) :])
        return d.ExecutionReport(
            execution_id=context.execution_id,
            plan_id=plan.plan_id,
            status=status,
            action_results=(*results, *remaining),
            output_started=started,
            error_code=error,
            retryable=retryable,
        )

    @staticmethod
    def _error_code(error, enum):
        if enum is d.HandlingErrorCode:
            return handling_error(error)
        if isinstance(error, d.SinkRejectedError):
            if error.code.name in {"STALE_INTERACTION", "SINK_CLOSED", "BACKPRESSURE_TIMEOUT"}:
                return enum[error.code.name]
            if enum is d.ExecutionErrorCode:
                return enum.UNSUPPORTED_OUTPUT if error.code is d.SinkRejectionCode.UNSUPPORTED_OUTPUT else enum.CONTRACT_MISMATCH
        if isinstance(error, TimeoutError):
            return enum.PROVIDER_TIMEOUT
        return enum.INTERNAL_ERROR

    @staticmethod
    def _check_sink(sink: object) -> None:
        if not callable(getattr(sink, "emit", None)):
            raise TypeError("sink must provide emit")

    def _record_exception(self, call_id, interaction_id, code, error):
        # traceback 的源码行也可能含密钥字面量；仅记录位置、类型，不格式化源码。
        safe_error = RuntimeError("Collaborator exception message omitted")
        locations = [(frame.f_code.co_filename, line, frame.f_code.co_name) for frame, line in walk_tb(error.__traceback__)]
        self._logger.error(
            "Agent collaborator failed character_id=%s call_id=%s interaction_id=%s error_code=%s type=%s stack=%s",
            self._character_id,
            call_id,
            interaction_id,
            code.value,
            type(error).__name__,
            locations,
            exc_info=(RuntimeError, safe_error, None),
        )

    def _record(self, call_id, interaction_id, status, error) -> None:
        log = self._logger.error if error is not None else self._logger.debug
        log(
            "Agent settlement character_id=%s call_id=%s interaction_id=%s status=%s error_code=%s",
            self._character_id,
            call_id,
            interaction_id,
            status.value,
            error.value if error else None,
        )
