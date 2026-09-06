"""本次调用的计划预检、顺序执行和失败报告。"""
from dataclasses import replace

import src.domain.agent as d
from src.agent.processing.plan_emitter import _DeliveryCancelled
from src.agent.processing.output_emitter import OutputEmitter
from .invocation import call_handler, _HandlerNotStarted


class Execution:
    """管理一次计划执行的内存状态，不读取历史执行或恢复输出。"""

    def __init__(self, agent, plan: d.ActionPlan, context: d.ExecutionContext,
                 sink: d.AgentOutputSink) -> None:
        """绑定门面、完整计划、执行上下文和本次输出接收器。"""
        self.agent, self.plan, self.context, self.sink = agent, plan, context, sink
        self.results: list[d.ActionResult] = []
        self.next_sequence = 0
        self.output_started = False

    def report(self, error: d.ExecutionErrorCode | None = None) -> d.ExecutionReport:
        """返回本次结果，未执行行动标记为未开始，且不要求调用者重试。"""
        status = (d.ExecutionStatus.CANCELLED if error is d.ExecutionErrorCode.CANCELLED
                  else d.ExecutionStatus.FAILED if error else d.ExecutionStatus.COMPLETED)
        return self.agent._execution_report(
            self.plan, self.context, status, error, self.results, self.output_started, False)

    async def run(self) -> d.ExecutionReport:
        """检查版本和取消状态，确认全部行动具有处理器后顺序执行。"""
        if self.plan.basis_interaction_revision != self.context.current_interaction_revision:
            return self.report(d.ExecutionErrorCode.STALE_INTERACTION)
        if self.context.cancellation.is_cancelled:
            return self.report(d.ExecutionErrorCode.CANCELLED)
        try:
            handlers = tuple(self.agent._action_router.resolve(action.kind) for action in self.plan.actions)
        except KeyError:
            return self.report(d.ExecutionErrorCode.UNSUPPORTED_ACTION)
        for action, handler in zip(self.plan.actions, handlers):
            if self.context.cancellation.is_cancelled:
                return self.report(d.ExecutionErrorCode.CANCELLED)
            outputs = OutputEmitter(self, action.action_id)
            result = None
            try:
                result = await call_handler(
                    self.agent,
                    lambda: handler.realize(action, self.context, outputs), self.context.cancellation,
                    self.context.execution_id, self.context.interaction_id)
                if (type(result) is not d.ActionResult or result.action_id != action.action_id
                        or result.status is d.ActionExecutionStatus.NOT_STARTED):
                    result = None
                    raise ValueError("invalid action result")
            except _HandlerNotStarted:
                return self.report(d.ExecutionErrorCode.CANCELLED)
            except Exception as error:
                code = (d.ExecutionErrorCode.CANCELLED if isinstance(error, _DeliveryCancelled)
                        else outputs.code or self.agent._error_code(error, d.ExecutionErrorCode))
                self.agent._record_exception(self.context.execution_id, self.context.interaction_id, code, error)
                result = result or self.agent._action_result(action)
                self.results.append(replace(
                    result, status=d.ActionExecutionStatus.CANCELLED if code is d.ExecutionErrorCode.CANCELLED
                    else d.ActionExecutionStatus.FAILED, error_code=code))
                return self.report(code)
            finally:
                outputs.close()
            if outputs.code is not None:
                # 处理器捕获交付异常后返回，也不能抹掉失败或继续后续行动。
                result = replace(
                    result, status=d.ActionExecutionStatus.CANCELLED
                    if outputs.code is d.ExecutionErrorCode.CANCELLED else d.ActionExecutionStatus.FAILED,
                    error_code=outputs.code,
                )
            self.results.append(result)
            if result.error_code is not None:
                return self.report(result.error_code)
            if self.context.cancellation.is_cancelled:
                return self.report(d.ExecutionErrorCode.CANCELLED)
        return self.report()
