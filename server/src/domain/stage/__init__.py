"""Stage 的通道无关输出与生命周期类型。"""
from .output import AgentPresentationChanged, AgentPresentationState, CancelDelivery, StageOutput
from .lifecycle import StageState, StageTerminationResult

__all__ = ["AgentPresentationChanged", "AgentPresentationState", "CancelDelivery",
           "StageOutput", "StageState", "StageTerminationResult"]
