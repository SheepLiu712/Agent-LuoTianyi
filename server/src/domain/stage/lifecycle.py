"""受管交互的生命周期、终止结果及连接附加契约。"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class StageState(str, Enum):
    """Stage 当前在线、离线保留、正在终止或已经终止。"""

    ONLINE = "online"
    OFFLINE = "offline"
    TERMINATING = "terminating"
    TERMINATED = "terminated"


class StageLifecycleState(str, Enum):
    PREPARING = "preparing"
    RUNNING = "running"
    TERMINATING = "terminating"
    TERMINATED = "terminated"


class StageEndReason(str, Enum):
    USER_REQUESTED = "user_requested"
    AGENT_REQUESTED = "agent_requested"
    IDLE_TIMEOUT = "idle_timeout"
    SWITCH = "switch"
    SHUTDOWN = "shutdown"
    INITIALIZATION_FAILED = "initialization_failed"
    TIME_LIMIT = "time_limit"
    SYSTEM_FAILURE = "system_failure"


class StageInitializationFailed(RuntimeError):
    """初始化失败，Stage 已接管失败清理。"""


class StageStartAborted(RuntimeError):
    """初始化完成前交互已经终止。"""


class StageHandoffFailed(RuntimeError):
    """原交互未安全、成功地完成切换收尾。"""


class StageShutdownFailed(RuntimeError):
    """仍有受管资源未安全释放，不允许继续关闭依赖。"""


@dataclass(frozen=True, slots=True, kw_only=True)
class StageTerminationResult:
    interaction_id: str
    reason: StageEndReason
    finalization_error: str | None = None
    cleanup_error: str | None = None
    resources_released: bool = True


class ManagedStage(Protocol):
    """Manager 的公共任务管理接口；接入归属与类型专用释放操作由登记记录保存。"""

    @property
    def interaction_id(self) -> str: ...

    @property
    def character_id(self) -> str: ...

    @property
    def lifecycle_state(self) -> StageLifecycleState: ...

    @property
    def interaction_ended(self) -> bool: ...

    async def start(self) -> None: ...

    def begin_termination(self, reason: StageEndReason) -> None: ...

    async def terminate(self, reason: StageEndReason) -> StageTerminationResult: ...


class ConnectedStage(Protocol):
    """连接事实和业务期限的消费接口；Manager 只负责计时，不解释业务状态。"""

    async def connection_changed(self, available: bool, generation: int) -> bool: ...

    async def expire_retention(self, deadline: float, generation: int) -> None: ...


StageInitializationOwner = Callable[[ManagedStage, Callable[[], Awaitable[None]]], asyncio.Task[None]]
StageTerminationOwner = Callable[
    [ManagedStage, Callable[[], Awaitable[StageTerminationResult]]], asyncio.Task[StageTerminationResult]
]
StageRetentionChanged = Callable[[ConnectedStage, float | None, int], None]
