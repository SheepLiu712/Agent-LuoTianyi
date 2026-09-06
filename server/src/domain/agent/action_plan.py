"""不可变行动与计划；只校验本身的值，不执行行动。"""
from abc import abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import ClassVar

from ._realization_contract import RealizationContractErrorCode as _Code, _Value
from .realization_enums import ActionKind, OutputDelivery, Visibility
from .stimulus_values import MediaRef


@dataclass(frozen=True, slots=True, kw_only=True)
class Tone(_Value):
    """非空白语气代码，具体映射由角色配置决定。"""
    value: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ChangeExpression(_Value):
    """说话或演唱附带的表情，包含非空白领域表情代码。"""
    expression_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class DynamicReplyTarget(_Value):
    """动态回复目标；parent_comment_id 为 None 表示回复原帖。"""
    dynamic_id: str
    parent_comment_id: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class DynamicSource(_Value):
    """动态的来源语义及稳定业务身份，用于来源追踪和业务去重。"""
    source_type: str
    source_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Action(_Value):
    """行动抽象基类，以显式 action_id 标识行动；非法字段抛出构造错误。"""
    _code = _Code.CONTRACT_INVALID_ACTION
    action_id: str

    @property
    @abstractmethod
    def kind(self) -> ActionKind:
        """返回具体行动固定的判别值。"""


@dataclass(frozen=True, slots=True, kw_only=True)
class StartThinking(Action):
    """Agent 已开始内容处理的通知，由 stage 消费的独立首计划承载。"""
    kind: ClassVar[ActionKind] = ActionKind.START_THINKING


@dataclass(frozen=True, slots=True, kw_only=True)
class Say(Action):
    """说话决定，区分显示与朗读文本；TTS 和预制音频互斥。

    空白显示文本只在有预制音频时合法，两个音频来源均为空表示纯文字。
    """
    kind: ClassVar[ActionKind] = ActionKind.SAY
    _blank_fields = ("content",)
    content: str
    sound_content: str | None
    prepared_audio_ref: MediaRef | None
    tone: Tone
    expression: ChangeExpression | None
    delivery: OutputDelivery

    def __post_init__(self):
        _Value.__post_init__(self)
        self._require(self.sound_content is None or self.prepared_audio_ref is None, "Conflicting audio sources")
        self._require(bool(self.content.strip()) or self.prepared_audio_ref is not None, "Missing display content")


@dataclass(frozen=True, slots=True, kw_only=True)
class Sing(Action):
    """演唱已确定的歌曲片段，可附带表情；衔接语由有序 Say 表达。"""
    kind: ClassVar[ActionKind] = ActionKind.SING
    song_id: str
    segment_id: str
    expression: ChangeExpression | None


@dataclass(frozen=True, slots=True, kw_only=True)
class WriteDiary(Action):
    """指定用户的当日日记正文，表达私密且禁止评论的日记发布决定。"""
    kind: ClassVar[ActionKind] = ActionKind.WRITE_DIARY
    owner_user_id: str
    local_date: date
    body: str


@dataclass(frozen=True, slots=True, kw_only=True)
class PublishDynamic(Action):
    """动态发布决定，包含正文、媒体、来源和可见性；私密发布必须指定用户。"""
    kind: ClassVar[ActionKind] = ActionKind.PUBLISH_DYNAMIC
    body: str
    media_refs: tuple[MediaRef, ...]
    visibility: Visibility
    owner_user_id: str | None
    source: DynamicSource
    allow_comment: bool

    def __post_init__(self):
        _Value.__post_init__(self)
        self._require(self.visibility is not Visibility.PRIVATE or self.owner_user_id is not None, "Missing private owner")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplyDynamic(Action):
    """向指定原帖或评论发布属于指定用户的回复正文。"""
    kind: ClassVar[ActionKind] = ActionKind.REPLY_DYNAMIC
    target: DynamicReplyTarget
    owner_user_id: str
    body: str


@dataclass(frozen=True, slots=True, kw_only=True)
class RequestSongLearning(Action):
    """请求学习指定歌曲，dedup_key 标识跨执行的同一业务请求。"""
    kind: ClassVar[ActionKind] = ActionKind.REQUEST_SONG_LEARNING
    song_id: str
    dedup_key: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ActionPlan(_Value):
    """一个请求产生的不可变有序计划，包含依据修订、刺激身份和非空行动。

    行动 ID 和来源刺激 ID 各自唯一；StartThinking 只能独占 ordinal 为零的计划。
    构造不查询请求记录或 stage，跨计划顺序由运行时维护。
    """
    _code = _Code.CONTRACT_INVALID_PLAN
    plan_id: str
    origin_request_id: str
    plan_ordinal: int
    target_character_id: str
    interaction_id: str
    basis_interaction_revision: int
    source_stimulus_ids: tuple[str, ...]
    actions: tuple[Action, ...]

    def __post_init__(self):
        _Value.__post_init__(self)
        ids = tuple(action.action_id for action in self.actions)
        self._require(bool(ids) and len(set(ids)) == len(ids), "Invalid action identities")
        self._require(len(set(self.source_stimulus_ids)) == len(self.source_stimulus_ids), "Duplicate source identity")
        if any(isinstance(action, StartThinking) for action in self.actions):
            self._require(len(self.actions) == 1 and self.plan_ordinal == 0, "Invalid thinking plan")
