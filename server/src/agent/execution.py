"""门面内部的执行协调：准入、逐行动结算与受限输出交付。"""
import asyncio
from dataclasses import replace

import src.domain.agent as d
from src.agent.ledgers._execution_codec import ActionFact, completed_prefix
from src.agent.planning.emitter import _DeliveryCancelled, _check_cancellation
from src.agent.planning.identity import encode_plan


class _HandlerNotStarted(_DeliveryCancelled):
    """处理器任务调度后、业务调用前已取消。"""


class _OutputIdentityError(ValueError):
    """处理器尝试交付不属于当前行动的输出。"""


class _StorageError(RuntimeError):
    """执行事实无法持久提交，禁止继续业务。"""


class _OutputDelivery:
    """串行投递单行动输出，独立累计未知与已确认事实。"""

    def __init__(self, execution, index):
        self._execution, self._index = execution, index
        self._lock = asyncio.Lock()
        self.error = None

    async def emit(self, output: d.AgentOutput) -> d.OutputReceipt:
        """持久登记后调用 sink，确认失败保留已知事实且封闭后续投递。"""
        async with self._lock:
            execution = self._execution
            if execution is None:
                raise RuntimeError("output delivery is closed")
            if self.error is not None:
                raise self.error
            context = execution.context
            _check_cancellation(context.cancellation)
            if (not isinstance(output, d.AgentOutput) or output.execution_id != context.execution_id
                    or output.interaction_id != context.interaction_id
                    or output.action_id != execution.plan.actions[self._index].action_id):
                raise _OutputIdentityError("output does not match action")
            fact = execution.facts[self._index]
            prior_unknown = fact.unknown
            fact.unknown = True
            try:
                execution.save()
                try:
                    receipt = await execution.sink.emit(output)
                except d.SinkRejectedError:
                    fact.unknown = prior_unknown
                    execution.save()
                    raise
                if (not isinstance(receipt, d.OutputReceipt) or receipt.execution_id != output.execution_id
                        or receipt.sequence_no != output.sequence_no):
                    raise ValueError("invalid output receipt")
                fact.confirmed, fact.unknown = True, prior_unknown
                execution.save()
            except _StorageError as error:
                self.error = error
                raise
            _check_cancellation(context.cancellation)
            return receipt

    def close(self):
        self._execution = None


class Execution:
    """单次 realize 的私有协调对象；共享持久账本但不共享调用上下文或 sink。"""

    def __init__(self, agent, plan, context, sink):
        self.agent, self.plan, self.context, self.sink = agent, plan, context, sink
        self.ledger = agent._execution_ledger
        self.facts = [ActionFact() for _ in plan.actions]
        self._failed_settlement_index = None

    def report(self, error=None, results=None, retryable=False):
        status = (d.ExecutionStatus.CANCELLED if error is d.ExecutionErrorCode.CANCELLED
                  else d.ExecutionStatus.FAILED if error else d.ExecutionStatus.COMPLETED)
        return self.agent._execution_report(
            self.plan, self.context, status, error,
            completed_prefix(self.facts) if results is None else results,
            any(fact.confirmed for fact in self.facts), retryable)

    def unavailable(self, error=None, results=None):
        if error is not None:
            self.agent._record_exception(self.context.execution_id, self.context.interaction_id,
                                         d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE, error)
        if results is None:
            results = completed_prefix(self.facts[:self._failed_settlement_index])
            index = len(results)
            if index < len(self.facts) and self.facts[index].started:
                known = self.facts[index].result or self.agent._action_result(self.plan.actions[index])
                results.append(replace(known, status=d.ActionExecutionStatus.FAILED,
                                       error_code=d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE))
        return self.report(d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE, results)

    def save(self):
        try:
            self.ledger.save(self.context.execution_id, self.facts)
        except Exception as error:
            raise _StorageError("execution storage unavailable") from error

    def historical(self):
        """终态优先于本次准入；未知开始不解释为安全的无效果失败。"""
        prefix = completed_prefix(self.facts)
        if len(prefix) == len(self.facts):
            return self.report()
        fact = self.facts[len(prefix)]
        if not fact.safe:
            result = fact.result or self.agent._action_result(
                self.plan.actions[len(prefix)], d.ActionExecutionStatus.FAILED,
                d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE)
            return self.report(result.error_code, [*prefix, result])

    async def run(self):
        try:
            payload = encode_plan(self.plan)
        except Exception as error:
            self.agent._record_exception(self.context.execution_id, self.context.interaction_id,
                                         d.ExecutionErrorCode.INTERNAL_ERROR, error)
            return self.report(d.ExecutionErrorCode.INTERNAL_ERROR)
        while True:
            try:
                state, facts = self.ledger.read(self.context.execution_id, payload)
                if facts is not None:
                    self.facts = facts
            except Exception as error:
                return self.unavailable(error)
            if state == "conflict":
                return self.report(d.ExecutionErrorCode.CONTRACT_MISMATCH, [])
            if state == "occupied":
                active = self.agent._executing.get(self.context.execution_id)
                if active is None or active[0] != payload:
                    return self.unavailable()
                result = await asyncio.shield(active[1])
                return result if result is not None else self.unavailable()
            terminal = self.historical()
            if terminal is not None:
                return terminal
            if self.plan.basis_interaction_revision != self.context.current_interaction_revision:
                return self.report(d.ExecutionErrorCode.STALE_INTERACTION)
            if self.context.cancellation.is_cancelled:
                return self.report(d.ExecutionErrorCode.CANCELLED)
            try:
                handlers = tuple(self.agent._action_router.resolve(action.kind) for action in self.plan.actions)
            except KeyError:
                return self.report(d.ExecutionErrorCode.UNSUPPORTED_ACTION)
            try:
                if self.ledger.claim(self.context.execution_id, payload, self.facts, new=state == "missing"):
                    break
            except Exception as error:
                return self.unavailable(error)
        outcome = asyncio.get_running_loop().create_future()
        self.agent._executing[self.context.execution_id] = payload, outcome
        result = None
        try:
            result = await self.actions(handlers)
        except asyncio.CancelledError:
            # 拥有者发布清理后的最新事实，等待者不使用加入时的旧快照。
            result = self.unavailable()
            raise
        finally:
            try:
                self.ledger.release(self.context.execution_id)
            except Exception as error:
                results = list(result.action_results) if result is not None else completed_prefix(self.facts)
                # 失败/取消项必须与整体错误一致，同时保留其效果。
                results = [replace(item, status=d.ActionExecutionStatus.FAILED,
                                   error_code=d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE)
                           if item.status in (d.ActionExecutionStatus.FAILED, d.ActionExecutionStatus.CANCELLED)
                           else item for item in results]
                result = self.unavailable(error, results)
            outcome.set_result(result)
            self.agent._executing.pop(self.context.execution_id, None)
        return result

    async def actions(self, handlers):
        results = completed_prefix(self.facts)
        for index in range(len(results), len(self.facts)):
            action, fact = self.plan.actions[index], self.facts[index]
            if self.context.cancellation.is_cancelled:
                return self.report(d.ExecutionErrorCode.CANCELLED, results, retryable=True)
            outputs = _OutputDelivery(self, index)

            async def execute():
                result = await handlers[index].realize(action, self.context, outputs)
                if (type(result) is not d.ActionResult or result.action_id != action.action_id
                        or result.status is d.ActionExecutionStatus.NOT_STARTED):
                    raise ValueError("invalid action result")
                fact.result = result
                try:
                    if outputs.error is not None:
                        raise outputs.error
                    self.save()  # 在拥有的 worker 内提交，取消清理正常返回也保存可信结果。
                except _StorageError:
                    self._failed_settlement_index = index
                    raise
                return result

            try:
                fact.started, fact.result = True, None
                self.save()
                result = await self.agent._call_handler(execute, self.context.cancellation,
                                                       self.context.execution_id, self.context.interaction_id)
            except _HandlerNotStarted:
                fact.started = False
                try:
                    self.save()
                except _StorageError as error:
                    return self.unavailable(error, results)
                return self.report(d.ExecutionErrorCode.CANCELLED, results, retryable=True)
            except Exception as error:
                code = (d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE if isinstance(error, _StorageError)
                        else d.ExecutionErrorCode.CANCELLED if isinstance(error, _DeliveryCancelled)
                        else self.agent._error_code(error, d.ExecutionErrorCode))
                self.agent._record_exception(self.context.execution_id, self.context.interaction_id, code, error)
                result = fact.result or self.agent._action_result(action)
                status = (d.ActionExecutionStatus.CANCELLED if code is d.ExecutionErrorCode.CANCELLED
                          else d.ActionExecutionStatus.FAILED)
                result = replace(result, status=status, error_code=code)
                return self.report(code, [*results, result])
            finally:
                outputs.close()
            results.append(result)
            if result.error_code is not None:
                return self.report(result.error_code, results, retryable=fact.safe)
            if self.context.cancellation.is_cancelled:
                return self.report(d.ExecutionErrorCode.CANCELLED, results, retryable=index + 1 < len(self.facts))
        return self.report(results=results)
