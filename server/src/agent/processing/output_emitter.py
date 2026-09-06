"""为本次执行的输出绑定身份和连续序号，失败后停止交付。"""
import asyncio
from dataclasses import fields
from src.utils.logger import get_logger

import src.domain.agent as d
from src.agent.processing.plan_emitter import _check_cancellation, _DeliveryCancelled
from . import output_drafts as drafts
from .output_drafts import OutputDraft


class OutputEmitter:
    """单个行动的输出入口；只在内存中记录本次交付结果。"""

    def __init__(self, execution, action_id: str) -> None:
        """绑定本次执行和当前行动标识。"""
        self._execution, self._action_id = execution, action_id
        self._lock = asyncio.Lock()
        self.error = None
        self.code = None

    async def emit(self, draft: OutputDraft) -> d.OutputReceipt:
        """校验并顺序交付一份输出，返回接收确认；首次失败后拒绝继续交付。"""
        async with self._lock:
            execution = self._execution
            if execution is None:
                raise RuntimeError("output emitter is closed")
            if self.error is not None:
                raise self.error
            context = execution.context
            _check_cancellation(context.cancellation)
            try:
                output_types = {
                    drafts.TextFinalDraft: d.TextFinalOutput,
                    drafts.AudioChunkDraft: d.AudioChunkOutput,
                    drafts.MessageEndDraft: d.MessageEndOutput,
                    drafts.ExpressionDraft: d.ExpressionOutput,
                }
                if type(draft) not in output_types:
                    raise ValueError("invalid output draft")
                sequence = execution.next_sequence
                output = output_types[type(draft)](
                    interaction_id=context.interaction_id, execution_id=context.execution_id,
                    action_id=self._action_id, sequence_no=sequence,
                    **{field.name: getattr(draft, field.name) for field in fields(draft)})
                receipt = await execution.sink.emit(output)
                if (type(receipt) is not d.OutputReceipt or receipt.execution_id != context.execution_id
                        or receipt.sequence_no != sequence):
                    raise ValueError("invalid output receipt")
                execution.output_started = True
                execution.next_sequence += 1
                _check_cancellation(context.cancellation)
                return receipt
            except _DeliveryCancelled:
                raise
            except asyncio.CancelledError as error:
                self.error = error
                self.code = d.ExecutionErrorCode.CANCELLED
                raise
            except Exception as error:
                self.error = error
                self.code = execution.agent._error_code(error, d.ExecutionErrorCode)
                execution.agent._record_exception(context.execution_id, context.interaction_id, self.code, error)
                get_logger(__name__).error(
                    "Output delivery failed character_id=%s execution_id=%s interaction_id=%s "
                    "action_id=%s sequence_no=%s error_code=%s",
                    execution.plan.target_character_id, context.execution_id, context.interaction_id,
                    self._action_id, execution.next_sequence, self.code.value,
                )
                raise

    def close(self) -> None:
        """结束当前行动的输出作用域，释放执行对象引用。"""
        self._execution = None
