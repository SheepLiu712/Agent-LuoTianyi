"""刺激的公共字段、具体事实类型及已登记的占位类型。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import ClassVar
from zoneinfo import ZoneInfo

from ._stimulus_contract import (
    InvalidStimulusError,
    _StimulusMeta,
    _raise_invalid,
    _require_aware_datetime,
    _require_instance,
    _require_nonblank_string,
    _require_nonnegative_int,
    _require_optional_instance,
    _require_optional_nonblank_string,
    _require_string_tuple,
    _require_tuple_of,
)
from .stimulus_values import (
    ActivityFact,
    BodyRegion,
    DynamicMessage,
    EvidenceRef,
    MediaRef,
    ProactiveReason,
    SongKnowledgeCandidate,
    SourceRef,
    TouchClickFrequency,
    WorldFact,
    WorldObservationKind,
)


class StimulusKind(str, Enum):
    """已登记刺激类型的稳定判别值，由具体类型固定。"""

    TEXT_MESSAGE = "text_message"
    IMAGE_MESSAGE = "image_message"
    VOICE_MESSAGE = "voice_message"
    USER_TYPING = "user_typing"
    IMAGE_SELECTION_OPENED = "image_selection_opened"
    IMAGE_SELECTION_CLOSED = "image_selection_closed"
    TOUCH_INTERACTION = "touch_interaction"
    TOY_VIBRATION = "toy_vibration"
    DEVICE_CONNECTED = "device_connected"
    DEVICE_DISCONNECTED = "device_disconnected"
    PROACTIVE_PROMPT_DUE = "proactive_prompt_due"
    INTERACTION_DEADLINE = "interaction_deadline"
    DYNAMIC_OBSERVED = "dynamic_observed"
    DIARY_PLANNING_DUE = "diary_planning_due"
    WORLD_OBSERVATION = "world_observation"
    DAILY_PLANNING_DUE = "daily_planning_due"
    ACTIVITY_DUE = "activity_due"
    ACTIVITY_STARTED = "activity_started"
    ACTIVITY_OBSERVATION = "activity_observation"
    ACTIVITY_ENDED = "activity_ended"
    SONG_KNOWLEDGE_DISCOVERED = "song_knowledge_discovered"
    SONG_LEARNED = "song_learned"


class StimulusSource(str, Enum):
    """刺激的语义来源：用户、设备、世界或交互流程。"""

    USER = "user"
    DEVICE = "device"
    WORLD = "world"
    STAGE = "stage"


class DynamicTargetKind(str, Enum):
    """本次动态观察的判断目标：原帖或评论。"""

    POST = "post"
    COMMENT = "comment"


@dataclass(frozen=True, slots=True, kw_only=True)
class Stimulus(ABC, metaclass=_StimulusMeta):
    """刺激的不可变公共字段；抽象基类不能直接构造。

    stimulus_id 标识事实，schema_version 当前仅接受整数 1，occurred_at
    记录带时区的发生时间。source、目标角色、可选用户及 ephemeral 均显式传入；
    ephemeral 表示事实是否仅在当前交互窗口内有意义。
    具体类型以关键字参数构造，非法字段抛出 InvalidStimulusError。
    """

    _constructible: ClassVar[bool] = True

    stimulus_id: str
    schema_version: int
    occurred_at: datetime
    source: StimulusSource
    target_character_ids: tuple[str, ...]
    user_id: str | None
    ephemeral: bool

    @property
    @abstractmethod
    def kind(self) -> StimulusKind:
        """返回具体刺激类型固定的判别值。"""

    def __post_init__(self) -> None:
        _validate_common_fields(
            stimulus_id=self.stimulus_id,
            schema_version=self.schema_version,
            occurred_at=self.occurred_at,
            source=self.source,
            target_character_ids=self.target_character_ids,
            user_id=self.user_id,
            ephemeral=self.ephemeral,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class TextMessage(Stimulus):
    """文本消息，包含非空白正文和客户端消息 ID；保留正文原值。"""

    kind: ClassVar[StimulusKind] = StimulusKind.TEXT_MESSAGE

    text: str
    client_msg_id: str

    def __post_init__(self) -> None:
        Stimulus.__post_init__(self)
        _require_nonblank_string(self.text)
        _require_nonblank_string(self.client_msg_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class ImageMessage(Stimulus):
    """图片消息，包含媒体引用、可选说明文字和客户端消息 ID。"""

    kind: ClassVar[StimulusKind] = StimulusKind.IMAGE_MESSAGE

    media_ref: MediaRef
    caption: str | None
    client_msg_id: str

    def __post_init__(self) -> None:
        Stimulus.__post_init__(self)
        _require_instance(self.media_ref, MediaRef)
        _require_optional_nonblank_string(self.caption)
        _require_nonblank_string(self.client_msg_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class VoiceMessage(Stimulus):
    """已结束的录音消息；媒体引用和非空白转写文本至少提供一种。"""

    kind: ClassVar[StimulusKind] = StimulusKind.VOICE_MESSAGE

    media_ref: MediaRef | None
    transcript: str | None
    client_msg_id: str

    def __post_init__(self) -> None:
        Stimulus.__post_init__(self)
        _require_optional_instance(self.media_ref, MediaRef)
        _require_optional_nonblank_string(self.transcript)
        _require_nonblank_string(self.client_msg_id)
        if self.media_ref is None and self.transcript is None:
            _raise_invalid()


@dataclass(frozen=True, slots=True, kw_only=True)
class UserTyping(Stimulus):
    """用户正在输入的协调信号，text_length 记录非负文本长度。"""

    kind: ClassVar[StimulusKind] = StimulusKind.USER_TYPING

    text_length: int

    def __post_init__(self) -> None:
        Stimulus.__post_init__(self)
        _require_nonnegative_int(self.text_length)


@dataclass(frozen=True, slots=True, kw_only=True)
class ImageSelectionOpened(Stimulus):
    """用户打开图片选择界面的协调信号，仅携带刺激公共字段。"""

    kind: ClassVar[StimulusKind] = StimulusKind.IMAGE_SELECTION_OPENED


@dataclass(frozen=True, slots=True, kw_only=True)
class ImageSelectionClosed(Stimulus):
    """用户关闭图片选择界面的协调信号，仅携带刺激公共字段。"""

    kind: ClassVar[StimulusKind] = StimulusKind.IMAGE_SELECTION_CLOSED


@dataclass(frozen=True, slots=True, kw_only=True)
class TouchInteraction(Stimulus):
    """客户端 Live2D 触摸事实，包含至少一个部位和可选的点击频率统计。"""

    kind: ClassVar[StimulusKind] = StimulusKind.TOUCH_INTERACTION

    body_regions: tuple[BodyRegion, ...]
    click_frequency: TouchClickFrequency | None

    def __post_init__(self) -> None:
        Stimulus.__post_init__(self)
        _require_tuple_of(self.body_regions, BodyRegion, allow_empty=False)
        _require_optional_instance(self.click_frequency, TouchClickFrequency)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProactivePromptDue(Stimulus):
    """主动提示到期事实，包含原因、带时区的到期时间、去重键和事实引用。"""

    kind: ClassVar[StimulusKind] = StimulusKind.PROACTIVE_PROMPT_DUE

    reason: ProactiveReason
    due_at: datetime
    dedup_key: str
    fact_refs: tuple[EvidenceRef, ...]

    def __post_init__(self) -> None:
        Stimulus.__post_init__(self)
        _require_instance(self.reason, ProactiveReason)
        _require_aware_datetime(self.due_at)
        _require_nonblank_string(self.dedup_key)
        _require_tuple_of(self.fact_refs, EvidenceRef)


@dataclass(frozen=True, slots=True, kw_only=True)
class InteractionDeadline(Stimulus):
    """交互已到强制重评时点的协调信号，仅携带刺激公共字段。"""

    kind: ClassVar[StimulusKind] = StimulusKind.INTERACTION_DEADLINE


@dataclass(frozen=True, slots=True, kw_only=True)
class DynamicObserved(Stimulus):
    """一次动态线程观察，包含有序消息、本次判断目标及非负修订号。

    首条消息是 ID 等于 dynamic_id 的原帖，后续评论的父消息必须已出现。
    消息 ID 唯一；target_message_id 必须存在且与原帖或评论的目标类型一致。
    """

    kind: ClassVar[StimulusKind] = StimulusKind.DYNAMIC_OBSERVED

    dynamic_id: str
    target_message_id: str
    target_kind: DynamicTargetKind
    messages: tuple[DynamicMessage, ...]
    revision: int

    def __post_init__(self) -> None:
        Stimulus.__post_init__(self)
        _require_nonblank_string(self.dynamic_id)
        _require_nonblank_string(self.target_message_id)
        _require_instance(self.target_kind, DynamicTargetKind)
        _require_tuple_of(self.messages, DynamicMessage, allow_empty=False)
        _require_nonnegative_int(self.revision)

        message_ids = tuple(message.message_id for message in self.messages)
        if len(message_ids) != len(set(message_ids)):
            _raise_invalid()
        if self.messages[0].message_id != self.dynamic_id:
            _raise_invalid()
        if self.messages[0].parent_message_id is not None:
            _raise_invalid()

        prior_ids = {self.dynamic_id}
        for message in self.messages[1:]:
            if message.parent_message_id not in prior_ids:
                _raise_invalid()
            prior_ids.add(message.message_id)

        if message_ids.count(self.target_message_id) != 1:
            _raise_invalid()
        if self.target_kind is DynamicTargetKind.POST:
            if self.target_message_id != self.dynamic_id:
                _raise_invalid()
        elif self.target_message_id == self.dynamic_id:
            _raise_invalid()


@dataclass(frozen=True, slots=True, kw_only=True)
class DiaryPlanningDue(Stimulus):
    """日记规划到期事实，以本地日期、ZoneInfo 时区和触发 ID 表达。"""

    kind: ClassVar[StimulusKind] = StimulusKind.DIARY_PLANNING_DUE

    local_date: date
    timezone: ZoneInfo
    trigger_id: str

    def __post_init__(self) -> None:
        Stimulus.__post_init__(self)
        if type(self.local_date) is not date:
            _raise_invalid()
        _require_instance(self.timezone, ZoneInfo)
        _require_nonblank_string(self.trigger_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class WorldObservation(Stimulus):
    """世界观察，包含观察类别、规范化事实、证据引用和非负世界修订号。"""

    kind: ClassVar[StimulusKind] = StimulusKind.WORLD_OBSERVATION

    observation_kind: WorldObservationKind
    fact: WorldFact
    evidence_refs: tuple[EvidenceRef, ...]
    world_revision: int

    def __post_init__(self) -> None:
        Stimulus.__post_init__(self)
        _require_instance(self.observation_kind, WorldObservationKind)
        _require_instance(self.fact, WorldFact)
        _require_tuple_of(self.evidence_refs, EvidenceRef)
        _require_nonnegative_int(self.world_revision)


@dataclass(frozen=True, slots=True, kw_only=True)
class ActivityObservation(Stimulus):
    """活动内观察，包含活动 ID、规范化事实和非负活动修订号。"""

    kind: ClassVar[StimulusKind] = StimulusKind.ACTIVITY_OBSERVATION

    activity_id: str
    observation: ActivityFact
    activity_revision: int

    def __post_init__(self) -> None:
        Stimulus.__post_init__(self)
        _require_nonblank_string(self.activity_id)
        _require_instance(self.observation, ActivityFact)
        _require_nonnegative_int(self.activity_revision)


@dataclass(frozen=True, slots=True, kw_only=True)
class SongKnowledgeDiscovered(Stimulus):
    """发现一首歌的知识候选，包含来源、外部歌曲 ID、修订号和抓取时间。"""

    kind: ClassVar[StimulusKind] = StimulusKind.SONG_KNOWLEDGE_DISCOVERED

    source_ref: SourceRef
    external_song_id: str
    revision: int
    candidate: SongKnowledgeCandidate
    fetched_at: datetime

    def __post_init__(self) -> None:
        Stimulus.__post_init__(self)
        _require_instance(self.source_ref, SourceRef)
        _require_nonblank_string(self.external_song_id)
        _require_nonnegative_int(self.revision)
        _require_instance(self.candidate, SongKnowledgeCandidate)
        _require_aware_datetime(self.fetched_at)


@dataclass(frozen=True, slots=True, kw_only=True)
class SongLearned(Stimulus):
    """歌曲学习完成事实，包含学习任务 ID、歌曲 ID 和带时区的完成时间。"""

    kind: ClassVar[StimulusKind] = StimulusKind.SONG_LEARNED

    learning_job_id: str
    song_id: str
    completed_at: datetime

    def __post_init__(self) -> None:
        Stimulus.__post_init__(self)
        _require_nonblank_string(self.learning_job_id)
        _require_nonblank_string(self.song_id)
        _require_aware_datetime(self.completed_at)


class ToyVibration(Stimulus):
    """玩偶振动占位类型；构造抛出 CONTRACT_STIMULUS_UNAVAILABLE 错误。"""

    _constructible = False
    kind = StimulusKind.TOY_VIBRATION


class DeviceConnected(Stimulus):
    """设备连接占位类型；构造抛出 CONTRACT_STIMULUS_UNAVAILABLE 错误。"""

    _constructible = False
    kind = StimulusKind.DEVICE_CONNECTED


class DeviceDisconnected(Stimulus):
    """设备断开占位类型；构造抛出 CONTRACT_STIMULUS_UNAVAILABLE 错误。"""

    _constructible = False
    kind = StimulusKind.DEVICE_DISCONNECTED


class DailyPlanningDue(Stimulus):
    """每日规划到期占位类型；构造抛出 CONTRACT_STIMULUS_UNAVAILABLE 错误。"""

    _constructible = False
    kind = StimulusKind.DAILY_PLANNING_DUE


class ActivityDue(Stimulus):
    """计划活动到达开始条件的占位类型；构造抛出 CONTRACT_STIMULUS_UNAVAILABLE 错误。"""

    _constructible = False
    kind = StimulusKind.ACTIVITY_DUE


class ActivityStarted(Stimulus):
    """活动开始占位类型；构造抛出 CONTRACT_STIMULUS_UNAVAILABLE 错误。"""

    _constructible = False
    kind = StimulusKind.ACTIVITY_STARTED


class ActivityEnded(Stimulus):
    """活动结束占位类型；构造抛出 CONTRACT_STIMULUS_UNAVAILABLE 错误。"""

    _constructible = False
    kind = StimulusKind.ACTIVITY_ENDED


def _validate_common_fields(
    *,
    stimulus_id: object,
    schema_version: object,
    occurred_at: object,
    source: object,
    target_character_ids: object,
    user_id: object,
    ephemeral: object,
) -> None:
    _require_nonblank_string(stimulus_id)
    if type(schema_version) is not int:
        _raise_invalid()
    if schema_version != 1:
        raise InvalidStimulusError(
            "Unsupported Stimulus schema version",
            code="CONTRACT_UNSUPPORTED_SCHEMA",
        )
    _require_aware_datetime(occurred_at)
    _require_instance(source, StimulusSource)
    _require_string_tuple(target_character_ids, allow_empty=False)
    _require_optional_nonblank_string(user_id)
    if type(ephemeral) is not bool:
        _raise_invalid()
