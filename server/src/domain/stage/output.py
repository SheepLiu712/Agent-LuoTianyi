"""Stage 向外部通道提交的业务输出和控制信号。"""
from dataclasses import dataclass
from enum import Enum

from src.domain.agent import AgentOutput


class AgentPresentationState(str, Enum):
    """角色的客户端呈现状态。"""

    THINKING = "thinking"
    WAITING = "waiting"


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentPresentationChanged:
    """指定 interaction_id 的角色进入 state 状态。"""

    interaction_id: str
    state: AgentPresentationState

    def __post_init__(self) -> None:
        if not isinstance(self.interaction_id, str) or not self.interaction_id.strip():
            raise ValueError("interaction_id must be nonblank")
        if not isinstance(self.state, AgentPresentationState):
            raise TypeError("state must be AgentPresentationState")


@dataclass(frozen=True, slots=True, kw_only=True)
class CancelDelivery:
    """丢弃指定交互、执行尚未发送的内容，并为已开始的消息发送空终止包。"""

    interaction_id: str
    execution_id: str

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value.strip()
               for value in (self.interaction_id, self.execution_id)):
            raise ValueError("interaction_id and execution_id must be nonblank")


StageOutput = AgentOutput | AgentPresentationChanged | CancelDelivery
"""Agent 业务输出、呈现状态变化或取消投递命令。"""
