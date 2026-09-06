"""调用方提供的接收协议、成功回执和明确拒绝错误。"""
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from ._realization_contract import RealizationContractErrorCode as _Code, _Value
from .action_plan import ActionPlan
from .execution_output import AgentOutput
from .realization_enums import OutputAcceptanceStatus, PlanAcceptanceStatus


class SinkRejectionCode(str, Enum):
    """接收器明确拒绝的原因，包括身份冲突、过时、关闭和背压超时。"""
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    CONTENT_CONFLICT = "CONTENT_CONFLICT"
    STALE_INTERACTION = "STALE_INTERACTION"
    UNSUPPORTED_OUTPUT = "UNSUPPORTED_OUTPUT"
    SINK_CLOSED = "SINK_CLOSED"
    BACKPRESSURE_TIMEOUT = "BACKPRESSURE_TIMEOUT"


class SinkRejectedError(Exception):
    """计划或输出被明确拒绝，code 是只读拒绝原因；不会返回成功回执。"""
    def __init__(self, message: str, *, code: SinkRejectionCode) -> None:
        self._code = code
        super().__init__(message)

    @property
    def code(self) -> SinkRejectionCode:
        """返回接收器明确拒绝的稳定原因。"""
        return self._code


@dataclass(frozen=True, slots=True, kw_only=True)
class PlanReceipt(_Value):
    """计划成功接收的身份和状态，不能据此认定业务行动已完成。"""
    _code = _Code.CONTRACT_INVALID_RECEIPT
    plan_id: str
    status: PlanAcceptanceStatus


@dataclass(frozen=True, slots=True, kw_only=True)
class OutputReceipt(_Value):
    """输出成功接收的身份和状态，不能据此认定音频已播放完成。"""
    _code = _Code.CONTRACT_INVALID_RECEIPT
    execution_id: str
    sequence_no: int
    status: OutputAcceptanceStatus


class ActionPlanSink(Protocol):
    """调用方提供的计划接收边界，按正常到达顺序接收完整计划。"""
    async def emit(self, plan: ActionPlan) -> PlanReceipt:
        """接收计划并返回成功回执；明确拒绝时抛出 SinkRejectedError。"""
        ...


class AgentOutputSink(Protocol):
    """调用方提供的输出接收边界，保持正常发送顺序与消息终止位置。"""
    async def emit(self, output: AgentOutput) -> OutputReceipt:
        """接收输出并返回成功回执；明确拒绝时抛出 SinkRejectedError。"""
        ...
