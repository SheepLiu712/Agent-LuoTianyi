"""由 stage 直接传入 Agent 的不可变交互事实快照。

快照以显式关键字参数构造，非法字段抛出 InvalidHandleInputError。
interaction_id 标识持续交互，interaction_revision 标识其非负修订号。
pending_stimuli 保留待处理刺激的顺序，ID 唯一且排除输入协调和期限信号。
now 带时区，timezone 为 ZoneInfo，supported_outputs 是允许为空的输出种类集合。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import ClassVar
from zoneinfo import ZoneInfo

from ._handle_input_contract import (
    HandleInputErrorCode,
    _HandleInputMeta,
    _aware,
    _nonblank,
    _require,
    _revision,
)
from .stimulus import Stimulus, StimulusKind


class InteractionKind(str, Enum):
    """交互快照的场景判别值：聊天、玩偶或世界。"""

    CHAT = "chat"
    TOY = "toy"
    WORLD = "world"


class ConnectionState(str, Enum):
    """聊天通道在快照时刻的连接状态：已连接或已断开。"""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"


class AgentOutputKind(str, Enum):
    """交互支持的输出种类：增量或完整文本、音频块、消息结束、表情及动作。"""

    TEXT_DELTA = "text_delta"
    TEXT_FINAL = "text_final"
    AUDIO_CHUNK = "audio_chunk"
    MESSAGE_END = "message_end"
    EXPRESSION = "expression"
    MOTION = "motion"


_COORDINATION_KINDS = frozenset({
    StimulusKind.USER_TYPING,
    StimulusKind.IMAGE_SELECTION_OPENED,
    StimulusKind.IMAGE_SELECTION_CLOSED,
    StimulusKind.INTERACTION_DEADLINE,
})


@dataclass(frozen=True, slots=True, kw_only=True)
class _InteractionFacts(metaclass=_HandleInputMeta):
    _error_code: ClassVar[HandleInputErrorCode] = HandleInputErrorCode.CONTRACT_INVALID_INTERACTION

    interaction_id: str
    interaction_revision: int
    user_id: str | None
    pending_stimuli: tuple[Stimulus, ...]
    now: datetime
    timezone: ZoneInfo
    supported_outputs: frozenset[AgentOutputKind]

    def __post_init__(self) -> None:
        _require(_nonblank(self.interaction_id), "interaction_id")
        _require(_revision(self.interaction_revision), "interaction_revision")
        _require(self.user_id is None or _nonblank(self.user_id), "user_id")
        _require(_aware(self.now), "now")
        _require(isinstance(self.timezone, ZoneInfo), "timezone")
        _require(type(self.supported_outputs) is frozenset, "supported_outputs")
        _require(
            all(isinstance(output, AgentOutputKind) for output in self.supported_outputs),
            "supported_outputs members",
        )
        _require(type(self.pending_stimuli) is tuple, "pending_stimuli")
        _require(all(isinstance(item, Stimulus) for item in self.pending_stimuli), "pending_stimuli members")
        _require(
            all(item.kind not in _COORDINATION_KINDS for item in self.pending_stimuli),
            "coordination signal in pending_stimuli",
        )
        ids = tuple(item.stimulus_id for item in self.pending_stimuli)
        _require(len(set(ids)) == len(ids), "duplicate pending stimulus_id")


@dataclass(frozen=True, slots=True, kw_only=True)
class ChatInteractionSnapshot(_InteractionFacts):
    """聊天交互的不可变快照，在公共事实上记录响应期限和连接状态。

    response_deadline 为 None 或带时区的时间，connection_state 使用连接状态枚举。
    """

    kind: ClassVar[InteractionKind] = InteractionKind.CHAT
    response_deadline: datetime | None
    connection_state: ConnectionState

    def __post_init__(self) -> None:
        _InteractionFacts.__post_init__(self)
        _require(self.response_deadline is None or _aware(self.response_deadline), "response_deadline")
        _require(isinstance(self.connection_state, ConnectionState), "connection_state")


@dataclass(frozen=True, slots=True, kw_only=True)
class ToyInteractionSnapshot(_InteractionFacts):
    """玩偶交互的不可变快照，在公共事实上记录非空白 device_id 和布尔 online。"""

    kind: ClassVar[InteractionKind] = InteractionKind.TOY
    device_id: str
    online: bool

    def __post_init__(self) -> None:
        _InteractionFacts.__post_init__(self)
        _require(_nonblank(self.device_id), "device_id")
        _require(type(self.online) is bool, "online")


@dataclass(frozen=True, slots=True, kw_only=True)
class WorldInteractionSnapshot(_InteractionFacts):
    """世界交互的不可变快照，记录世界、活动、规划周期的身份及相应修订号。

    world_revision 与 schedule_revision 为非负整数；activity_id 和
    activity_revision 同时存在或同时为 None，planning_cycle_id 可为 None。
    """

    kind: ClassVar[InteractionKind] = InteractionKind.WORLD
    world_id: str
    world_revision: int
    activity_id: str | None
    activity_revision: int | None
    planning_cycle_id: str | None
    schedule_revision: int

    def __post_init__(self) -> None:
        _InteractionFacts.__post_init__(self)
        _require(_nonblank(self.world_id), "world_id")
        _require(_revision(self.world_revision), "world_revision")
        _require(_revision(self.schedule_revision), "schedule_revision")
        _require(self.activity_id is None or _nonblank(self.activity_id), "activity_id")
        _require(self.activity_revision is None or _revision(self.activity_revision), "activity_revision")
        _require((self.activity_id is None) == (self.activity_revision is None), "activity identity/revision pair")
        _require(self.planning_cycle_id is None or _nonblank(self.planning_cycle_id), "planning_cycle_id")


InteractionSnapshot = ChatInteractionSnapshot | ToyInteractionSnapshot | WorldInteractionSnapshot
"""聊天、玩偶与世界三种具体快照的联合类型。"""
