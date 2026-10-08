"""交互上下文使用的数据类型。"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from src.domain.memory_context import MemoryHit


def _check_terms(values: tuple[str, ...]) -> None:
    if not isinstance(values, tuple) or any(not isinstance(value, str) for value in values):
        raise TypeError("词条应为字符串元组")


@dataclass(frozen=True)
class ContextIdentity:
    """上下文所属的角色、交互及用户；无用户的交互使用 None。"""

    character_id: str
    interaction_id: str
    user_id: str | None

    def __post_init__(self) -> None:
        for value in (self.character_id, self.interaction_id, self.user_id):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError("上下文标识不能为空")
        if self.character_id is None or self.interaction_id is None:
            raise ValueError("角色和交互标识不能为空")


@dataclass(frozen=True)
class UserProfile:
    """用户画像；description 是已保存的用户描述。"""

    description: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.description, str):
            raise TypeError("description 应为字符串")


@dataclass(frozen=True)
class UserPreferences:
    """用户期望的关系、表达风格、性格特点和补充说明。"""

    relationship: str = ""
    speaking_style: str = ""
    personality_traits: tuple[str, ...] = ()
    custom_context: str = ""
    personality_text: str = ""

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str)
            for value in (
                self.relationship,
                self.speaking_style,
                self.custom_context,
                self.personality_text,
            )
        ):
            raise TypeError("偏好的文字字段应为字符串")
        _check_terms(self.personality_traits)


@dataclass(frozen=True)
class UserContextSnapshot:
    """一次读取获得的用户画像和偏好。"""

    profile: UserProfile = UserProfile()
    preferences: UserPreferences = UserPreferences()


@dataclass(frozen=True)
class TextContent:
    """文本对话内容及输入时提取的关键词。"""

    text: str
    terms: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("text 应为字符串")
        _check_terms(self.terms)


@dataclass(frozen=True)
class ImageContent:
    """图片说明、受控媒体身份、兼容文件位置、媒体类型及关键词。"""

    text: str
    image_client_path: str | None = None
    image_server_path: str | None = None
    mime_type: str | None = None
    terms: tuple[str, ...] = ()
    media_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or any(
            value is not None and not isinstance(value, str)
            for value in (self.image_client_path, self.image_server_path, self.mime_type, self.media_id)
        ):
            raise TypeError("图片文字和位置字段应为字符串")
        _check_terms(self.terms)


class AudioUnderstandingStatus(str, Enum):
    """音频是否得到可用理解。"""

    UNDERSTOOD = "understood"
    NOT_UNDERSTOOD = "not_understood"


def render_audio_context(
    *,
    status: AudioUnderstandingStatus,
    transcript: str | None,
    emotion: str | None,
    sound_description: str | None,
) -> str:
    """唯一的音频上下文规范文本拼接入口。"""
    if status is AudioUnderstandingStatus.NOT_UNDERSTOOD:
        return "[音频]听不清"
    clauses: list[str] = []
    if transcript:
        if emotion:
            clauses.append(f"用户带着{emotion}的情绪说：“{transcript}”")
        else:
            clauses.append(f"用户说：“{transcript}”")
    if sound_description:
        clauses.append(sound_description)
    return "[音频]" + "；".join(clauses)


@dataclass(frozen=True, kw_only=True)
class AudioContent:
    """结构化音频理解及其确定性上下文文本。"""

    media_id: str
    mime_type: str
    duration_ms: int
    understanding_status: AudioUnderstandingStatus
    transcript: str | None
    emotion: str | None
    sound_description: str | None
    text: str = field(init=False)

    def __post_init__(self) -> None:
        self._validate_media()
        self._validate_understanding()
        object.__setattr__(
            self,
            "text",
            render_audio_context(
                status=self.understanding_status,
                transcript=self.transcript,
                emotion=self.emotion,
                sound_description=self.sound_description,
            ),
        )

    def _validate_media(self) -> None:
        if not isinstance(self.understanding_status, AudioUnderstandingStatus):
            raise TypeError("understanding_status 应为 AudioUnderstandingStatus")
        if not isinstance(self.media_id, str) or not self.media_id.strip():
            raise ValueError("media_id 不能为空")
        if not isinstance(self.mime_type, str) or not self.mime_type.startswith("audio/"):
            raise ValueError("mime_type 应为音频类型")
        if type(self.duration_ms) is not int or self.duration_ms <= 0:
            raise ValueError("duration_ms 应为正整数")

    def _validate_understanding(self) -> None:
        fields = (self.transcript, self.emotion, self.sound_description)
        if any(value is not None and not isinstance(value, str) for value in fields):
            raise TypeError("音频理解字段应为字符串或 None")
        if any(value is not None and not value.strip() for value in fields):
            raise ValueError("音频理解字段不能是空白字符串")
        if self.understanding_status is AudioUnderstandingStatus.NOT_UNDERSTOOD:
            if any(value is not None for value in fields):
                raise ValueError("未理解音频不能包含理解字段")
        elif self.transcript is None and self.sound_description is None:
            raise ValueError("已理解音频必须包含转写或声音描述")
        if self.emotion is not None and self.transcript is None:
            raise ValueError("没有转写时不能包含情绪")


@dataclass(frozen=True)
class SongContent:
    """演唱记录的文字、曲名和片段名称。"""

    text: str
    song: str
    segment: str | None = None


@dataclass(frozen=True)
class ConversationEntry:
    """一条正式对话；entry_id 对应历史记录 UUID，source 为发言来源。"""

    entry_id: str
    timestamp: datetime
    source: str
    content: TextContent | ImageContent | AudioContent | SongContent

    def __post_init__(self) -> None:
        if not self.entry_id.strip() or not self.source.strip():
            raise ValueError("对话标识和来源不能为空")
        if not isinstance(self.timestamp, datetime) or self.timestamp.tzinfo is not None:
            raise ValueError("timestamp 应为不带时区的服务器本地时间")
        if not isinstance(self.content, (TextContent, ImageContent, AudioContent, SongContent)):
            raise TypeError("content 应为对话内容类型")


@dataclass(frozen=True)
class ConversationSummary:
    """已经压缩的对话总结。"""

    text: str = ""


@dataclass(frozen=True)
class ConversationSnapshot:
    """对话总结与按时间排列的未压缩对话。"""

    summary: ConversationSummary = ConversationSummary()
    entries: tuple[ConversationEntry, ...] = ()


@dataclass(frozen=True)
class ConversationCompaction:
    """外部生成的压缩结果，记录生成依据和被覆盖的对话 ID。"""

    previous_summary: ConversationSummary
    covered_entry_ids: tuple[str, ...]
    summary: ConversationSummary

    def __post_init__(self) -> None:
        if not isinstance(self.previous_summary, ConversationSummary) or not isinstance(
            self.summary, ConversationSummary
        ):
            raise TypeError("原总结和新总结应为 ConversationSummary")
        _check_terms(self.covered_entry_ids)
        if not self.covered_entry_ids or any(not value.strip() for value in self.covered_entry_ids):
            raise ValueError("被覆盖的对话 ID 不能为空")
        if len(set(self.covered_entry_ids)) != len(self.covered_entry_ids):
            raise ValueError("被覆盖的对话 ID 不能重复")
        if not isinstance(self.summary.text, str) or not self.summary.text.strip():
            raise ValueError("新总结不能为空")


@dataclass(frozen=True)
class JargonExplanation:
    """关键词及其术语解释。"""

    keyword: str
    explanation: str


@dataclass(frozen=True)
class RecallEntry:
    """召回缓存记录；stimulus_id 指向触发该结果的刺激。"""

    entry_id: str
    stimulus_id: str
    content: MemoryHit | JargonExplanation

    def __post_init__(self) -> None:
        if not self.entry_id.strip() or not self.stimulus_id.strip():
            raise ValueError("召回记录和刺激标识不能为空")
        if not isinstance(self.content, (MemoryHit, JargonExplanation)):
            raise TypeError("召回内容须为 MemoryHit 或 JargonExplanation")
