"""门面内部的执行协调：准入、逐行动结算与受限输出交付。"""
import asyncio
from dataclasses import replace

import src.domain.agent as d
from src.agent.ledgers._execution_codec import ActionFact, completed_prefix
from src.agent.planning.emitter import _DeliveryCancelled
from src.agent.planning.identity import encode_plan
from src.agent.outputs.emitter import OutputEmitter
from src.agent.ledgers.output_outbox import OutputStorageError as _StorageError


class _HandlerNotStarted(_DeliveryCancelled):
    """处理器任务调度后、业务调用前已取消。"""


class Execution:
    """单次 realize 的私有协调对象；共享持久账本但不共享调用上下文或 sink。"""

    def __init__(self, agent, plan, context, sink):
        self.agent, self.plan, self.context, self.sink = agent, plan, context, sink
        self.ledger = agent._execution_ledger
        self.facts = [ActionFact() for _ in plan.actions]
        self._failed_settlement_index = None
        self.slots = []

    def report(self, error=None, results=None, retryable=False):
        status = (d.ExecutionStatus.CANCELLED if error is d.ExecutionErrorCode.CANCELLED
                  else d.ExecutionStatus.FAILED if error else d.ExecutionStatus.COMPLETED)
        return self.agent._execution_report(
            self.plan, self.context, status, error,
            self.prefix() if results is None else results,
            any(fact.confirmed for fact in self.facts), retryable)

    def unavailable(self, error=None, results=None):
        if error is not None:
            self.agent._record_exception(self.context.execution_id, self.context.interaction_id,
                                         d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE, error)
        if results is None:
            results = self.prefix()[:self._failed_settlement_index]
            index = len(results)
            if index < len(self.facts) and self.facts[index].started:
                known = self.facts[index].result or self.agent._action_result(self.plan.actions[index])
                results.append(replace(known, status=d.ActionExecutionStatus.FAILED,
                                       error_code=d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE))
        return self.report(d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE, results)

    def save(self):
        try:
            self.ledger.save(self.context.execution_id, self.facts, self.slots)
        except Exception as error:
            raise _StorageError("execution storage unavailable") from error

    def pending(self, index):
        return next((slot for slot in self.slots
                     if slot.output.action_id == self.plan.actions[index].action_id and slot.state != "ACCEPTED"), None)

    def prefix(self):
        results = completed_prefix(self.facts)
        for index in range(len(results)):
            if self.facts[index].unknown or self.pending(index):
                return results[:index]
        return results

    def output_only(self, index):
        """可信完成或不可重做的行动，仅恢复其安全待投递输出。"""
        fact = self.facts[index]
        return (fact.result is not None and not fact.unknown and self.pending(index) is not None
                and (fact.complete or not fact.safe))

    def admission(self, error):
        """准入仅投影本次报告，保留恢复行动的效果及原持久结算。"""
        results = self.prefix()
        index = len(results)
        if index < len(self.facts) and self.output_only(index):
            result = self.facts[index].result
            if self.facts[index].complete:
                result = replace(result, status=d.ActionExecutionStatus.ALREADY_COMPLETED)
            else:
                result = self.project(result, error)
            results.append(result)
        return self.report(error, results)

    @staticmethod
    def project(result, error):
        """以本次失败或取消投影行动，保留已知效果而不修改账本事实。"""
        status = (d.ActionExecutionStatus.CANCELLED if error is d.ExecutionErrorCode.CANCELLED
                  else d.ActionExecutionStatus.FAILED)
        return replace(result, status=status, error_code=error)

    def settle(self, index, outputs):
        """可信结果与内存已确认回执一起提交；本次存储失败仍向上报告。"""
        try:
            if outputs.payload_lost:
                raise outputs.error
            self.save()
            if isinstance(outputs.error, _StorageError):
                raise outputs.error
        except _StorageError:
            self._failed_settlement_index = index
            raise

    def historical(self):
        """终态优先于本次准入；未知开始不解释为安全的无效果失败。"""
        prefix = self.prefix()
        if len(prefix) == len(self.facts):
            return self.report()
        fact = self.facts[len(prefix)]
        if fact.unknown or (fact.started and fact.result is None):
            return self.unavailable()
        if self.output_only(len(prefix)):
            return None
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
                state, facts, slots = self.ledger.read(self.context.execution_id, payload)
                if facts is not None:
                    self.facts = facts
                self.slots = slots or []
                if slots is None and any(fact.confirmed or fact.unknown for fact in self.facts):
                    if not all(fact.complete and not fact.unknown for fact in self.facts):
                        return self.unavailable()
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
                return self.admission(d.ExecutionErrorCode.STALE_INTERACTION)
            if self.context.cancellation.is_cancelled:
                return self.admission(d.ExecutionErrorCode.CANCELLED)
            try:
                handlers = tuple(self.agent._action_router.resolve(action.kind) for action in self.plan.actions)
            except KeyError:
                return self.admission(d.ExecutionErrorCode.UNSUPPORTED_ACTION)
            try:
                if self.ledger.claim(self.context.execution_id, payload, self.facts, new=state == "missing", legacy=slots is None):
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
        results = self.prefix()
        for index in range(len(results), len(self.facts)):
            action, fact = self.plan.actions[index], self.facts[index]
            recovery = self.output_only(index)
            if self.context.cancellation.is_cancelled:
                if recovery:
                    return self.admission(d.ExecutionErrorCode.CANCELLED)
                return self.report(d.ExecutionErrorCode.CANCELLED, results, retryable=True)
            outputs = OutputEmitter(self, index)
            previous = replace(fact)

            async def execute():
                if recovery:
                    try:
                        await outputs._recover()
                    except _StorageError:
                        self.settle(index, outputs)
                    except (d.SinkRejectedError, _DeliveryCancelled):
                        pass
                    return (replace(fact.result, status=d.ActionExecutionStatus.ALREADY_COMPLETED)
                            if fact.complete else fact.result)
                result = await handlers[index].realize(action, self.context, outputs)
                if (type(result) is not d.ActionResult or result.action_id != action.action_id
                        or result.status is d.ActionExecutionStatus.NOT_STARTED):
                    raise ValueError("invalid action result")
                fact.result = result
                self.settle(index, outputs)  # 取消清理正常返回也在拥有的 worker 内持久结算。
                return result

            try:
                if not recovery:
                    fact.started, fact.result = True, None
                    self.save()
                result = await self.agent._call_handler(execute, self.context.cancellation,
                                                       self.context.execution_id, self.context.interaction_id)
            except _HandlerNotStarted:
                fact.started, fact.result = previous.started, previous.result
                try:
                    self.save()
                except _StorageError as error:
                    return self.unavailable(error, results)
                return (self.admission(d.ExecutionErrorCode.CANCELLED) if recovery else
                        self.report(d.ExecutionErrorCode.CANCELLED, results, retryable=True))
            except Exception as error:
                code = (d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE if isinstance(error, _StorageError)
                        else d.ExecutionErrorCode.CANCELLED if isinstance(error, _DeliveryCancelled)
                        else outputs.code or self.agent._error_code(error, d.ExecutionErrorCode))
                self.agent._record_exception(self.context.execution_id, self.context.interaction_id, code, error)
                result = fact.result or self.agent._action_result(action)
                result = self.project(result, code)
                return self.report(code, [*results, result])
            finally:
                outputs.close()
            # 协作取消不改写可信行动结果；未知与未确认输出仍独立阻断推进。
            delivery_failed = outputs.error is not None and not isinstance(outputs.error, _DeliveryCancelled)
            if delivery_failed or fact.unknown or (fact.complete and self.pending(index)):
                code = outputs.code or d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE
                result = self.project(result, code)
                return self.report(code, [*results, result], retryable=not delivery_failed and not fact.unknown)
            results.append(result)
            if result.error_code is not None:
                return self.report(result.error_code, results, retryable=fact.safe or self.pending(index) is not None)
            if self.context.cancellation.is_cancelled:
                return self.report(d.ExecutionErrorCode.CANCELLED, results, retryable=index + 1 < len(self.facts))
        return self.report(results=results)
