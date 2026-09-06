"""角色门面：校验、内部路由、单次交付结算及在途调用所有权。"""
import asyncio
from collections.abc import Callable
from dataclasses import replace
from traceback import walk_tb

from sqlalchemy.orm import Session

import src.domain.agent as d
from src.agent.execution import Execution, _HandlerNotStarted, _OutputIdentityError
from src.agent.ledgers.execution_ledger import ExecutionLedger
from src.agent.handlers.action.router import ActionHandler, ActionRouter
from src.agent.handlers.stimulus.router import StimulusHandler, StimulusRouter
from src.agent.ledgers._request_codec import fingerprint
from src.agent.ledgers.request_ledger import RequestLedger
from src.agent.planning.emitter import PlanEmitter, _DeliveryCancelled, handling_error
from src.utils.logger import get_logger


def _retryable(error):
    return error is not None and error.name in {"PROVIDER_TIMEOUT", "BACKPRESSURE_TIMEOUT"}


class Agent:
    """角色的两接口业务门面，内部委托已注册处理器并结算接收与效果事实。

    AgentRuntime 装配角色私有路由并管理接受状态；生产注册表为空。
    请求账本保存终态及待恢复计划，同身份重投不重复认知；接收器只属于单次调用。
    """

    __slots__ = ("_character_id", "_accepting", "_logger", "_stimulus_router", "_action_router",
                 "_inflight", "_request_ledger", "_handling", "_execution_ledger", "_executing")

    def __init__(self, *, character_id: str,
                 sql_session_factory: Callable[[], Session],
                 stimulus_router: StimulusRouter[StimulusHandler] | None = None,
                 action_router: ActionRouter[ActionHandler] | None = None) -> None:
        """绑定角色、会话工厂和内部路由；空白角色抛 ValueError，账本初始化失败向上传播。

        会话工厂由运行时注入并用于现有数据库，省略路由使用空注册表。
        """
        if not isinstance(character_id, str) or not character_id.strip():
            raise ValueError("Agent requires a nonblank character_id")
        self._character_id = character_id
        self._accepting = True
        self._logger = get_logger(__name__)
        self._stimulus_router = stimulus_router if stimulus_router is not None else StimulusRouter(())
        self._action_router = action_router if action_router is not None else ActionRouter(())
        self._inflight: set[asyncio.Future] = set()
        self._request_ledger = RequestLedger(character_id, sql_session_factory)
        self._handling: dict[str, tuple[str, asyncio.Future]] = {}
        self._execution_ledger = ExecutionLedger(character_id, sql_session_factory)
        self._executing: dict[str, tuple[str, asyncio.Future]] = {}

    def _stop_accepting(self) -> None:
        self._accepting = False

    def _begin_call(self):
        completion = asyncio.get_running_loop().create_future()
        self._inflight.add(completion)
        return completion

    def _end_call(self, completion):
        completion.set_result(None)
        self._inflight.discard(completion)

    async def _call_handler(self, call, cancellation, call_id, interaction_id):
        # 门面拥有处理器任务；调用方重复取消不能再次取消其正在进行的清理。
        async def run():
            if cancellation.is_cancelled:
                raise _HandlerNotStarted()
            return await call()

        worker = asyncio.create_task(run())
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
        """校验并登记刺激，交付稳定计划并持久结算；重投读取终态或恢复原计划。

        相同 ID 的不同内容拒绝；并发重复等待原调用，等待者取消不影响拥有者。
        恢复仅交付已存计划，不重跑处理器；存储或未结算占用返回依赖失败。
        参数错误抛 TypeError。协作取消保留已确认事实；认知任务取消保留占用，
        恢复任务取消在清理及可信结算后释放恢复权，两者均传播 CancelledError。
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
        completion = self._begin_call()
        try:
            report = await self._handle_registered(request, plan_sink)
            self._record(request.request_id, request.interaction.interaction_id,
                         report.request_status, report.error_code)
            return report
        finally:
            self._end_call(completion)

    def _storage_failure(self, request, error=None, emitted=()):
        code = d.HandlingErrorCode.DEPENDENCY_UNAVAILABLE
        if error is not None:
            self._record_exception(request.request_id, request.interaction.interaction_id, code, error)
        return self._handling_failure(request, d.HandlingRequestStatus.FAILED, code, emitted)

    async def _handle_registered(self, request, sink):
        try:
            identity = fingerprint(self._character_id, request)
            state, report = self._request_ledger.claim(request.request_id, identity)
            if state in {"terminal", "recovery"}:
                self._validate_handling_report(request, report, report.emitted_plan_ids)
                if state == "terminal":
                    return report
        except Exception as error:
            return self._storage_failure(request, error)
        if state == "conflict":
            return self._handling_failure(request, d.HandlingRequestStatus.FAILED,
                                          d.HandlingErrorCode.CONTRACT_SNAPSHOT_MISMATCH)
        if state == "occupied":
            active = self._handling.get(request.request_id)
            if active is None or active[0] != identity:
                return self._storage_failure(request)
            result = await asyncio.shield(active[1])
            return result if result is not None else self._storage_failure(request)
        outcome = asyncio.get_running_loop().create_future()
        self._handling[request.request_id] = identity, outcome
        result, plans = None, None
        try:
            try:
                plans = PlanEmitter(self._character_id, request, sink, self._request_ledger.outbox,
                                    recovery=state == "recovery")
            except Exception as error:
                return self._storage_failure(request, error)
            if state == "recovery":
                result = await self._recover(request, plans, report, identity)
            else:
                result = plans.finish(await self._handle_once(request, plans))
            try:
                self._request_ledger.settle(request.request_id, identity, result, plans.accepted_ids)
            except Exception as error:
                result = self._storage_failure(request, error, result.emitted_plan_ids)
                return result
            if state == "recovery" and request.cancellation.is_cancelled:
                result = replace(result, request_status=d.HandlingRequestStatus.CANCELLED,
                                 error_code=None, retryable=False)
            return result
        finally:
            if plans is not None:
                plans.close()
            outcome.set_result(result)
            self._handling.pop(request.request_id)

    async def _recover(self, request, plans, provisional, identity):
        if request.cancellation.is_cancelled:
            return provisional
        try:
            await self._call_handler(plans.recover, request.cancellation,
                                     request.request_id, request.interaction.interaction_id)
        except asyncio.CancelledError:
            # 受控接收器任务已经完成清理；此时才能释放恢复权并传播调用取消。
            try:
                self._request_ledger.settle(request.request_id, identity,
                                           plans.finish(provisional, recovery=True), plans.accepted_ids)
            except Exception as error:
                self._storage_failure(request, error)
            raise
        except Exception:
            pass
        return plans.finish(provisional, recovery=True)

    async def _handle_once(self, request, plan_sink):
        status, error = d.HandlingRequestStatus.FAILED, None
        if request.cancellation.is_cancelled:
            status = d.HandlingRequestStatus.CANCELLED
        else:
            try:
                handler = self._stimulus_router.resolve(request.stimulus.kind)
            except KeyError:
                error = d.HandlingErrorCode.UNSUPPORTED_STIMULUS
            else:
                return await self._handle(request, plan_sink, handler)
        report = self._handling_failure(request, status, error)
        return report

    async def _handle(self, request, plans, handler):
        try:
            try:
                report = await self._call_handler(lambda: handler.handle(request, plans), request.cancellation,
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
            return report
        except asyncio.CancelledError:
            self._record(request.request_id, request.interaction.interaction_id,
                         d.HandlingRequestStatus.CANCELLED, None)
            raise

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
        """持久校验执行身份，预检全计划并顺序执行；重投跳过已完成行动。

        可信无效果且无已确认/未知输出的失败允许原执行安全继续；存储失败或
        未结算的开始状态阻止重做。相同执行的并发等待者共享拥有者报告。
        类型错误抛 TypeError；任务取消在可信结果持久结算和清理后传播。
        """
        if not isinstance(plan, d.ActionPlan) or not isinstance(execution_context, d.ExecutionContext):
            raise TypeError("plan and execution_context must be domain objects")
        self._check_sink(output_sink)
        context = execution_context
        error = None
        if plan.target_character_id != self._character_id or plan.interaction_id != context.interaction_id:
            error = d.ExecutionErrorCode.CONTRACT_MISMATCH
        elif not self._accepting:
            error = d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE
        if error is not None:
            report = self._execution_report(plan, context, d.ExecutionStatus.FAILED, error, [], False, False)
        else:
            completion = self._begin_call()
            try:
                report = await Execution(self, plan, context, output_sink).run()
            except asyncio.CancelledError:
                self._record(context.execution_id, context.interaction_id,
                             d.ExecutionStatus.CANCELLED, d.ExecutionErrorCode.CANCELLED)
                raise
            finally:
                self._end_call(completion)
        self._record(context.execution_id, context.interaction_id, report.status, report.error_code)
        return report

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
        if enum is d.HandlingErrorCode:
            return handling_error(error)
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
        # traceback 的源码行也可能含密钥字面量；仅记录位置、类型，不格式化源码。
        safe_error = RuntimeError("Collaborator exception message omitted")
        locations = [(frame.f_code.co_filename, line, frame.f_code.co_name)
                     for frame, line in walk_tb(error.__traceback__)]
        self._logger.error(
            "Agent collaborator failed character_id=%s call_id=%s interaction_id=%s error_code=%s type=%s stack=%s",
            self._character_id, call_id, interaction_id, code.value, type(error).__name__,
            locations, exc_info=(RuntimeError, safe_error, None),
        )

    def _record(self, call_id, interaction_id, status, error) -> None:
        self._logger.info(
            "Agent settlement character_id=%s call_id=%s interaction_id=%s status=%s error_code=%s",
            self._character_id, call_id, interaction_id, status.value, error.value if error else None,
        )
