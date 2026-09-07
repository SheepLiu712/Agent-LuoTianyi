"""交互上下文使用的数据类型。"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

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
        if any(not isinstance(value, str) for value in (
            self.relationship, self.speaking_style, self.custom_context, self.personality_text,
        )):
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
    """图片描述、文件位置、媒体类型及关键词。"""

    text: str
    image_client_path: str | None = None
    image_server_path: str | None = None
    mime_type: str | None = None
    terms: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or any(value is not None and not isinstance(value, str)
                for value in (self.image_client_path, self.image_server_path, self.mime_type)):
            raise TypeError("图片文字和位置字段应为字符串")
        _check_terms(self.terms)


@dataclass(frozen=True)
class AudioContent:
    """音频对话在历史记录中保存的文字内容。"""

    text: str


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
class CompactionPolicy:
    """未压缩条数超过 threshold 时生成总结，保留最后 keep_recent 条。"""

    threshold: int = 60
    keep_recent: int = 30

    def __post_init__(self) -> None:
        if not 0 <= self.keep_recent <= self.threshold:
            raise ValueError("压缩阈值须满足 0 <= keep_recent <= threshold")


@dataclass(frozen=True)
class CompactionResult:
    """本次是否完成压缩，以及操作后的对话上下文。"""

    compacted: bool
    snapshot: ConversationSnapshot


class ConversationSummarizer(Protocol):
    """对话总结能力；由调用方注入模型及提示词配置。"""

    async def summarize(self, snapshot: ConversationSnapshot) -> ConversationSummary:
        """根据旧总结与待压缩对话生成新总结，失败时抛出异常。"""
        ...


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
