"""触摸预制反应的资源选择技能。"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

import src.domain.agent as d
from src.agent.skills.contracts import SkillInvocation
from src.agent.skills.expression._touch_resources import TouchFastReplyBuilder
from src.agent.skills.expression.prepared_speech import PreparedSpeechCatalog
from src.utils.logger import get_logger

_DEFAULT_REGIONS = frozenset(
    {
        "head",
        "body",
        "legs",
        "hands",
        "头",
        "辫子",
        "耳机",
        "袖",
        "左腿",
        "右腿",
        "身体",
        "裙子",
        "8",
        "左手",
        "右手",
    }
)
_DEFAULT_MAX_TOUCHES_10S = 8
_DEFAULT_MAX_TOUCHES_30S = 16


def _positive_int(value: object, name: str, default: int) -> int:
    """校验频率上限；缺省时沿用默认值，非法值直接报错。"""
    if value is None:
        return default
    if type(value) is not int:
        raise TypeError(f"touch policy {name} must be an integer")
    if value <= 0:
        raise ValueError(f"touch policy {name} must be a positive integer")
    return value


def _regions(value: object, default: frozenset[str]) -> frozenset[str]:
    """校验允许的区域别名集合；缺省时沿用默认集合。"""
    if value is None:
        return default
    if isinstance(value, (str, bytes)) or not isinstance(value, Iterable):
        raise TypeError("touch policy allowed_regions must be a collection of region names")
    regions = tuple(value)
    if not regions or any(not isinstance(item, str) or not item.strip() for item in regions):
        raise ValueError("touch policy allowed_regions must contain nonblank region names")
    return frozenset(regions)


@dataclass(frozen=True, slots=True)
class TouchPolicy:
    """按已知区域和 10/30 秒聚合频率上限决定是否接受快速反应。

    频率窗口由领域 `TouchClickFrequency` 固定（10 秒 / 30 秒），可配置的是
    **上限**与**允许的区域别名**；默认值保持旧链行为。
    """

    allowed_regions: frozenset[str] = _DEFAULT_REGIONS
    max_touches_10s: int = _DEFAULT_MAX_TOUCHES_10S
    max_touches_30s: int = _DEFAULT_MAX_TOUCHES_30S

    def __post_init__(self) -> None:
        if isinstance(self.allowed_regions, (str, bytes)) or not isinstance(self.allowed_regions, Iterable):
            raise TypeError("touch policy allowed_regions must be a collection of region names")
        regions = tuple(self.allowed_regions)
        if not regions or any(not isinstance(item, str) or not item.strip() for item in regions):
            raise ValueError("touch policy allowed_regions must contain nonblank region names")
        for name in ("max_touches_10s", "max_touches_30s"):
            value = getattr(self, name)
            if type(value) is not int:
                raise TypeError(f"touch policy {name} must be an integer")
            if value <= 0:
                raise ValueError(f"touch policy {name} must be a positive integer")

    @classmethod
    def from_config(cls, config: object = None) -> "TouchPolicy":
        """从角色 `reflex.touch.fast_reply.policy` 读取策略；缺省或未提供时用默认值。"""
        if config is None:
            return cls()
        if not isinstance(config, Mapping):
            raise TypeError("touch policy config must be a mapping")
        defaults = cls()
        return cls(
            allowed_regions=_regions(config.get("allowed_regions"), defaults.allowed_regions),
            max_touches_10s=_positive_int(config.get("max_touches_10s"), "max_touches_10s", defaults.max_touches_10s),
            max_touches_30s=_positive_int(config.get("max_touches_30s"), "max_touches_30s", defaults.max_touches_30s),
        )

    def allows(self, stimulus: d.TouchInteraction) -> bool:
        """仅接受已知区域，且 10/30 秒计数不超过配置上限。"""
        if any(region.value not in self.allowed_regions for region in stimulus.body_regions):
            return False
        frequency = stimulus.click_frequency
        return frequency is None or (
            frequency.count_10s <= self.max_touches_10s and frequency.count_30s <= self.max_touches_30s
        )


@dataclass(frozen=True, slots=True)
class TouchReaction:
    """一次可用触摸反应的预制音频引用和目标表情。"""

    audio_ref: d.MediaRef
    expression_id: str


class TouchReactionSkill:
    """共享所有角色的触摸策略和预制资源选择器。"""

    def __init__(
        self,
        configs: Mapping[str, Mapping[str, object]],
        prepared_speech: PreparedSpeechCatalog,
    ) -> None:
        """按角色配置一次性构造选择器；调用时由 SkillInvocation 选择。"""
        self._resources = {
            character_id: self._build(character_id, config, prepared_speech)
            for character_id, config in configs.items()
            if config
        }

    @staticmethod
    def _build(
        character_id: str,
        config: Mapping[str, object],
        prepared_speech: PreparedSpeechCatalog,
    ) -> tuple[TouchFastReplyBuilder, dict[object, str], TouchPolicy]:
        try:
            entries = prepared_speech.entries(character_id)
        except KeyError:
            raise ValueError(f"touch fast reply requires prepared speech catalog for {character_id}") from None
        builder = TouchFastReplyBuilder(config, entries)
        media_ids = {entry.audio_path: entry.name for entry in entries}
        return builder, media_ids, TouchPolicy.from_config(config.get("policy"))

    def allows(self, invocation: SkillInvocation, stimulus: d.TouchInteraction) -> bool:
        """按本次角色的策略判断快速反应是否允许。"""
        resources = self._resources.get(invocation.character_id)
        return resources is not None and resources[2].allows(stimulus)

    def choose(self, invocation: SkillInvocation, stimulus: d.TouchInteraction) -> TouchReaction | None:
        """返回可读取的随机触摸资源；未命中或资源失败时返回 None。"""
        resources = self._resources.get(invocation.character_id)
        if resources is None:
            return None
        builder, media_ids, _policy = resources
        if not builder.should_use_fast_path():
            get_logger(__name__).error("Touch fast path missed")
            return None
        audio_path = builder.pick_audio_file()
        if audio_path is None:
            return None
        try:
            Path(audio_path).read_bytes()
        except OSError:
            get_logger(__name__).exception("Touch voice read failed path=%s", audio_path)
            return None
        expression_id = builder.expression_for(audio_path) or "normal"
        return TouchReaction(
            audio_ref=d.MediaRef(media_id=media_ids[audio_path]),
            expression_id=expression_id,
        )
