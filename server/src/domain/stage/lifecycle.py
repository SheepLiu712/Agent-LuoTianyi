"""聊天交互的生命周期结果。"""
from dataclasses import dataclass
from enum import Enum

from src.domain.agent import HandlingReport


class StageState(str, Enum):
    """Stage 当前在线、离线保留、正在终止或已经终止。"""

    ONLINE = "online"
    OFFLINE = "offline"
    TERMINATING = "terminating"
    TERMINATED = "terminated"


@dataclass(frozen=True, slots=True, kw_only=True)
class StageTerminationResult:
    """终止处理报告及失败说明；report 为空表示未能取得 Agent 报告。"""

    report: HandlingReport | None
    error: str | None
