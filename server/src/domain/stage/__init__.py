"""Stage 的通道无关输出、提醒端口与生命周期类型。"""

from .lifecycle import StageState, StageTerminationResult
from .output import AgentPresentationChanged, AgentPresentationState, CancelDelivery, StageOutput

__all__ = [
    "AgentPresentationChanged",
    "AgentPresentationState",
    "CancelDelivery",
    "StageOutput",
    "StageState",
    "StageTerminationResult",
]
