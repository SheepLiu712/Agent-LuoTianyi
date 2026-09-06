"""为处理器草稿分配持久身份，确认前不允许后续输出。"""
import asyncio
from traceback import walk_tb

import src.domain.agent as d
from src.agent.ledgers._output_codec import bind, encode
from src.agent.ledgers.output_outbox import OutputStorageError
from src.agent.planning.emitter import _DeliveryCancelled, _check_cancellation
from src.utils.logger import get_logger
from .drafts import OutputDraft


class _ContentConflict(ValueError):
    """同一持久槽位出现不同内容。"""


class _UnknownDelivery(RuntimeError):
    """已有无法确认的输出，禁止重新进入外部接收器。"""


class OutputEmitter:
    """单行动内容生产入口；拥有者退出后关闭，不暴露外部接收器。"""

    def __init__(self, execution, index):
        self._execution, self._index = execution, index
        self._lock = asyncio.Lock()
        self.error = None
        self.code = None
        self.payload_lost = False

    async def emit(self, draft: OutputDraft) -> d.OutputReceipt:
        """校验草稿并持久投递；明确拒绝可同值重试，其余错误封闭本次输出。"""
        return await self._deliver(draft)

    async def _recover(self) -> d.OutputReceipt:
        """由执行协调器投递已有槽位的原值，不分配身份或再次生成内容。"""
        return await self._deliver(None, recovery=True)

    async def _deliver(self, draft, *, recovery=False):
        async with self._lock:
            execution = self._execution
            if execution is None:
                raise RuntimeError("output emitter is closed")
            if self.error is not None:
                raise self.error
            context = execution.context
            action_id = execution.plan.actions[self._index].action_id
            pending = execution.pending(self._index)
            sequence = pending.output.sequence_no if pending else len(execution.slots)
            try:
                _check_cancellation(context.cancellation)
                if pending and pending.state == "UNKNOWN":
                    raise _UnknownDelivery("output receipt unknown")
                output = pending.output if recovery else bind(draft, context, action_id, sequence)
                payload = encode(output)
                if pending and payload != encode(pending.output):
                    raise _ContentConflict("output slot content changed")
                if pending is None:
                    try:
                        pending = execution.ledger.outbox.prepare(context.execution_id, output)
                    except Exception as error:
                        self.payload_lost = True
                        raise OutputStorageError("output prepare failed") from error
                    execution.slots.append(pending)
                fact = execution.facts[self._index]
                prior_state, prior_unknown = pending.state, fact.unknown
                pending.state, fact.unknown = "UNKNOWN", True
                try:
                    execution.save()
                except OutputStorageError:
                    # 外部调用尚未开始，最终结算只能保存原本已持久的安全槽位。
                    pending.state, fact.unknown = prior_state, prior_unknown
                    raise
                try:
                    receipt = await execution.sink.emit(pending.output)
                except d.SinkRejectedError:
                    pending.state, fact.unknown = "REJECTED", False
                    execution.save()
                    raise
                if (type(receipt) is not d.OutputReceipt or receipt.execution_id != context.execution_id
                        or receipt.sequence_no != sequence):
                    raise ValueError("invalid output receipt")
                pending.state, fact.confirmed, fact.unknown = "ACCEPTED", True, False
                execution.save()
                self.code = None
                _check_cancellation(context.cancellation)
                return receipt
            except Exception as error:
                self.code = (d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE
                             if isinstance(error, (OutputStorageError, _UnknownDelivery))
                             else d.ExecutionErrorCode.CANCELLED if isinstance(error, _DeliveryCancelled)
                             else d.ExecutionErrorCode.CONTRACT_MISMATCH if isinstance(error, _ContentConflict)
                             else execution.agent._error_code(error, d.ExecutionErrorCode))
                if not isinstance(error, d.SinkRejectedError):
                    self.error = error
                get_logger(__name__).error(
                    "Output failed character_id=%s execution_id=%s interaction_id=%s action_id=%s "
                    "sequence=%s error_code=%s type=%s stack=%s",
                    execution.plan.target_character_id, context.execution_id, context.interaction_id,
                    action_id, sequence, self.code.value, type(error).__name__,
                    [(frame.f_code.co_filename, line, frame.f_code.co_name) for frame, line in walk_tb(error.__traceback__)])
                raise

    def close(self):
        """撤销处理器持有的本次投递能力。"""
        self._execution = None
