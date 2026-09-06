"""角色门面：校验、内部路由、单次交付结算及在途调用所有权。"""
import asyncio
from dataclasses import replace

import src.domain.agent as d
from src.agent.handlers.action.router import ActionHandler, ActionRouter
from src.agent.handlers.stimulus.router import StimulusHandler, StimulusRouter
from src.utils.logger import get_logger


class _DeliveryCancelled(Exception):
    """协作式取消，区别于调用任务收到的 CancelledError。"""


class _OutputIdentityError(ValueError):
    """处理器尝试交付不属于当前行动的输出。"""


class _PlanDelivery:
    """保存单次请求的已接收计划，并在调用结束后释放外部接收器。"""

    def __init__(self, character_id, request, sink):
        self._character_id = character_id
        self._request = request
        self._sink = sink
        self.accepted_ids: list[str] = []

    async def emit(self, plan: d.ActionPlan) -> d.PlanReceipt:
        if self._sink is None:
            raise RuntimeError("plan delivery is closed")
        _check_cancellation(self._request.cancellation)
        request = self._request
        sources = {s.stimulus_id for s in (request.stimulus, *request.interaction.pending_stimuli)}
        if (not isinstance(plan, d.ActionPlan)
                or plan.target_character_id != self._character_id
                or plan.origin_request_id != request.request_id
                or plan.interaction_id != request.interaction.interaction_id
                or plan.basis_interaction_revision != request.interaction.interaction_revision
                or not set(plan.source_stimulus_ids).issubset(sources)):
            raise ValueError("plan does not match request")
        receipt = await self._sink.emit(plan)
        if not isinstance(receipt, d.PlanReceipt) or receipt.plan_id != plan.plan_id:
            raise ValueError("invalid plan receipt")
        if plan.plan_id not in self.accepted_ids:
            self.accepted_ids.append(plan.plan_id)
        _check_cancellation(request.cancellation)
        return receipt

    def close(self):
        self._sink = None
        self._request = None


class _OutputDelivery:
    """限制单项行动的输出身份，独立记录已确认输出事实。"""

    def __init__(self, action_id, context, sink):
        self._action_id = action_id
        self._context = context
        self._sink = sink
        self.started = False

    async def emit(self, output: d.AgentOutput) -> d.OutputReceipt:
        if self._sink is None:
            raise RuntimeError("output delivery is closed")
        _check_cancellation(self._context.cancellation)
        if (not isinstance(output, d.AgentOutput)
                or output.execution_id != self._context.execution_id
                or output.interaction_id != self._context.interaction_id
                or output.action_id != self._action_id):
            raise _OutputIdentityError("output does not match action")
        receipt = await self._sink.emit(output)
        if (not isinstance(receipt, d.OutputReceipt)
                or receipt.execution_id != output.execution_id
                or receipt.sequence_no != output.sequence_no):
            raise ValueError("invalid output receipt")
        self.started = True
        _check_cancellation(self._context.cancellation)
        return receipt

    def close(self):
        self._sink = None
        self._context = None


def _check_cancellation(token):
    if token.is_cancelled:
        raise _DeliveryCancelled()


def _retryable(error):
    return error is not None and error.name in {"PROVIDER_TIMEOUT", "BACKPRESSURE_TIMEOUT"}


class Agent:
    """角色的两接口业务门面，内部委托已注册处理器并结算接收与效果事实。

    AgentRuntime 装配角色私有路由并管理接受状态；生产注册表为空。
    请求、交互、接收器和报告属于单次调用，不共享当前用户状态。
    """

    __slots__ = ("_character_id", "_accepting", "_logger", "_stimulus_router", "_action_router", "_inflight")

    def __init__(self, *, character_id: str,
                 stimulus_router: StimulusRouter[StimulusHandler] | None = None,
                 action_router: ActionRouter[ActionHandler] | None = None) -> None:
        """绑定角色并注入内部路由；省略路由使用空表，空白角色抛 ValueError。"""
        if not isinstance(character_id, str) or not character_id.strip():
            raise ValueError("Agent requires a nonblank character_id")
        self._character_id = character_id
        self._accepting = True
        self._logger = get_logger(__name__)
        self._stimulus_router = stimulus_router if stimulus_router is not None else StimulusRouter(())
        self._action_router = action_router if action_router is not None else ActionRouter(())
        self._inflight: set[asyncio.Future] = set()

    def _stop_accepting(self) -> None:
        self._accepting = False

    def _begin_call(self):
        completion = asyncio.get_running_loop().create_future()
        self._inflight.add(completion)
        return completion

    def _end_call(self, completion):
        completion.set_result(None)
        self._inflight.discard(completion)

    async def _call_handler(self, awaitable, call_id, interaction_id):
        # 门面拥有处理器任务；调用方重复取消不能再次取消其正在进行的清理。
        worker = asyncio.create_task(awaitable)
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            worker.cancel()
            while not worker.done():
                try:
                    await asyncio.shield(worker)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if not worker.cancelled():
                cleanup_error = worker.exception()
                if cleanup_error is not None:
                    self._record_exception(call_id, interaction_id,
                                           d.ExecutionErrorCode.INTERNAL_ERROR, cleanup_error)
            raise

    async def handle_stimulus(self, request: d.HandleStimulusRequest,
                              plan_sink: d.ActionPlanSink) -> d.HandlingReport:
        """校验并路由刺激，通过本次 plan_sink 交付计划，返回消费及接收事实。

        参数类型错误抛 TypeError；入口拒绝保留全部 pending。协作者错误转为
        稳定失败报告，协作取消保留已确认事实；任务取消在处理器清理后传播。
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
        elif request.cancellation.is_cancelled:
            status = d.HandlingRequestStatus.CANCELLED
        else:
            try:
                handler = self._stimulus_router.resolve(request.stimulus.kind)
            except KeyError:
                error = d.HandlingErrorCode.UNSUPPORTED_STIMULUS
            else:
                return await self._handle(request, plan_sink, handler)
        report = self._handling_failure(request, status, error)
        self._record(request.request_id, request.interaction.interaction_id, status, error)
        return report

    async def _handle(self, request, sink, handler):
        completion = self._begin_call()
        plans = _PlanDelivery(self._character_id, request, sink)
        try:
            try:
                report = await self._call_handler(handler.handle(request, plans),
                                                  request.request_id, request.interaction.interaction_id)
                self._validate_handling_report(request, report, plans.accepted_ids)
                if request.cancellation.is_cancelled:
                    report = replace(report, request_status=d.HandlingRequestStatus.CANCELLED,
                                     error_code=None, retryable=False)
            except _DeliveryCancelled:
                report = self._handling_failure(request, d.HandlingRequestStatus.CANCELLED,
                                                None, plans.accepted_ids)
            except Exception as error:
                code = self._error_code(error, d.HandlingErrorCode)
                self._record_exception(request.request_id, request.interaction.interaction_id, code, error)
                report = self._handling_failure(request, d.HandlingRequestStatus.FAILED,
                                                code, plans.accepted_ids, _retryable(code))
            self._record(request.request_id, request.interaction.interaction_id,
                         report.request_status, report.error_code)
            return report
        except asyncio.CancelledError:
            self._record(request.request_id, request.interaction.interaction_id,
                         d.HandlingRequestStatus.CANCELLED, None)
            raise
        finally:
            plans.close()
            self._end_call(completion)

    @staticmethod
    def _validate_handling_report(request, report, accepted_ids):
        pending = tuple(item.stimulus_id for item in request.interaction.pending_stimuli)
        if (not isinstance(report, d.HandlingReport)
                or report.request_id != request.request_id
                or report.trigger_stimulus_id != request.stimulus.stimulus_id
                or report.basis_interaction_revision != request.interaction.interaction_revision
                or report.emitted_plan_ids != tuple(accepted_ids)
                or tuple(i for i in pending if i in report.considered_pending_stimulus_ids)
                != report.considered_pending_stimulus_ids):
            raise ValueError("invalid handler settlement")

    @staticmethod
    def _handling_failure(request, status, error, emitted=(), retryable=False):
        pending = tuple(item.stimulus_id for item in request.interaction.pending_stimuli)
        return d.HandlingReport(
            request_id=request.request_id, request_status=status,
            trigger_stimulus_id=request.stimulus.stimulus_id,
            basis_interaction_revision=request.interaction.interaction_revision,
            considered_pending_stimulus_ids=pending, consumed_pending_stimulus_ids=(),
            retained_pending_stimulus_ids=pending, emitted_plan_ids=tuple(emitted),
            reconsider_at=None, error_code=error, retryable=retryable,
        )

    async def realize_action_plan(self, plan: d.ActionPlan, execution_context: d.ExecutionContext,
                                  output_sink: d.AgentOutputSink) -> d.ExecutionReport:
        """整份计划预检后顺序执行，向本次 output_sink 投递并返回逐行动结果。

        身份、修订、关闭及路由拒绝均不开始行动。失败或取消停止后续行动，
        保留已确认输出与效果；参数错误抛 TypeError，任务取消在清理后传播。
        """
        if not isinstance(plan, d.ActionPlan) or not isinstance(execution_context, d.ExecutionContext):
            raise TypeError("plan and execution_context must be domain objects")
        self._check_sink(output_sink)
        context = execution_context
        status = d.ExecutionStatus.FAILED
        if plan.target_character_id != self._character_id or plan.interaction_id != context.interaction_id:
            error = d.ExecutionErrorCode.CONTRACT_MISMATCH
        elif plan.basis_interaction_revision != context.current_interaction_revision:
            error = d.ExecutionErrorCode.STALE_INTERACTION
        elif not self._accepting:
            error = d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE
        elif context.cancellation.is_cancelled:
            status, error = d.ExecutionStatus.CANCELLED, d.ExecutionErrorCode.CANCELLED
        else:
            try:
                handlers = tuple(self._action_router.resolve(action.kind) for action in plan.actions)
            except KeyError:
                error = d.ExecutionErrorCode.UNSUPPORTED_ACTION
            else:
                return await self._realize(plan, context, output_sink, handlers)
        report = self._execution_report(plan, context, status, error, [], False, False)
        self._record(context.execution_id, context.interaction_id, status, error)
        return report

    async def _realize(self, plan, context, sink, handlers):
        completion = self._begin_call()
        results = []
        started = False
        status, error = d.ExecutionStatus.COMPLETED, None
        try:
            for action, handler in zip(plan.actions, handlers):
                if context.cancellation.is_cancelled:
                    status, error = d.ExecutionStatus.CANCELLED, d.ExecutionErrorCode.CANCELLED
                    break
                outputs = _OutputDelivery(action.action_id, context, sink)
                try:
                    result = await self._call_handler(handler.realize(action, context, outputs),
                                                      context.execution_id, context.interaction_id)
                    if (not isinstance(result, d.ActionResult) or result.action_id != action.action_id
                            or result.status is d.ActionExecutionStatus.NOT_STARTED):
                        raise ValueError("invalid action result")
                except _DeliveryCancelled:
                    result = self._action_result(action, d.ActionExecutionStatus.CANCELLED,
                                                 d.ExecutionErrorCode.CANCELLED)
                except Exception as exception:
                    code = self._error_code(exception, d.ExecutionErrorCode)
                    self._record_exception(context.execution_id, context.interaction_id, code, exception)
                    result = self._action_result(action, d.ActionExecutionStatus.FAILED, code)
                finally:
                    started = started or outputs.started
                    outputs.close()
                results.append(result)
                if result.status in (d.ActionExecutionStatus.FAILED, d.ActionExecutionStatus.CANCELLED):
                    status, error = d.ExecutionStatus(result.status.value), result.error_code
                    break
                if context.cancellation.is_cancelled:
                    status, error = d.ExecutionStatus.CANCELLED, d.ExecutionErrorCode.CANCELLED
                    break
            report = self._execution_report(plan, context, status, error, results, started, _retryable(error))
            self._record(context.execution_id, context.interaction_id, status, error)
            return report
        except asyncio.CancelledError:
            self._record(context.execution_id, context.interaction_id,
                         d.ExecutionStatus.CANCELLED, d.ExecutionErrorCode.CANCELLED)
            raise
        finally:
            self._end_call(completion)

    @staticmethod
    def _action_result(action, status=d.ActionExecutionStatus.NOT_STARTED, error=None):
        return d.ActionResult(action_id=action.action_id, status=status, error_code=error,
                              irreversible_effect_committed=False, effect_ref=None)

    def _execution_report(self, plan, context, status, error, results, started, retryable):
        remaining = tuple(self._action_result(action) for action in plan.actions[len(results):])
        return d.ExecutionReport(execution_id=context.execution_id, plan_id=plan.plan_id, status=status,
                                 action_results=(*results, *remaining), output_started=started,
                                 error_code=error, retryable=retryable)

    @staticmethod
    def _error_code(error, enum):
        if isinstance(error, d.SinkRejectedError):
            if error.code.name in {"STALE_INTERACTION", "SINK_CLOSED", "BACKPRESSURE_TIMEOUT"}:
                return enum[error.code.name]
            if enum is d.ExecutionErrorCode:
                return (enum.UNSUPPORTED_OUTPUT if error.code is d.SinkRejectionCode.UNSUPPORTED_OUTPUT
                        else enum.CONTRACT_MISMATCH)
        if isinstance(error, TimeoutError):
            return enum.PROVIDER_TIMEOUT
        if isinstance(error, _OutputIdentityError):
            return enum.CONTRACT_MISMATCH
        return enum.INTERNAL_ERROR

    @staticmethod
    def _check_sink(sink: object) -> None:
        if not callable(getattr(sink, "emit", None)):
            raise TypeError("sink must provide emit")

    def _record_exception(self, call_id, interaction_id, code, error):
        # 原异常可能包含模型输入或密钥；保留栈位置和类型，不保存其正文及局部变量。
        safe_error = RuntimeError("Collaborator exception message omitted")
        self._logger.error(
            "Agent collaborator failed character_id=%s call_id=%s interaction_id=%s error_code=%s type=%s",
            self._character_id, call_id, interaction_id, code.value, type(error).__name__,
            exc_info=(RuntimeError, safe_error, error.__traceback__),
        )

    def _record(self, call_id, interaction_id, status, error) -> None:
        self._logger.info(
            "Agent settlement character_id=%s call_id=%s interaction_id=%s status=%s error_code=%s",
            self._character_id, call_id, interaction_id, status.value, error.value if error else None,
        )
