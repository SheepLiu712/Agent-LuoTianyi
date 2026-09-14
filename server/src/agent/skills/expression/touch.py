"""触摸预制反应的资源选择技能。"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import src.domain.agent as d
from src.agent.reflex.touch import TouchFastReplyBuilder
from src.resources.prepared_speech import load_prepared_speech
from src.utils.logger import get_logger

_SUPPORTED_REGIONS = frozenset({
    "head", "body", "legs", "hands", "头", "辫子", "耳机", "袖",
    "左腿", "右腿", "身体", "裙子", "8", "左手", "右手",
})
_MAX_TOUCHES_10S = 8
_MAX_TOUCHES_30S = 16


@dataclass(frozen=True, slots=True)
class TouchPolicy:
    """按旧触摸区域和聚合频率决定是否接受快速反应。"""

    def allows(self, stimulus: d.TouchInteraction) -> bool:
        """仅接受已知区域，且 10/30 秒计数不超过限流阈值。"""
        if any(region.value not in _SUPPORTED_REGIONS for region in stimulus.body_regions):
            return False
        frequency = stimulus.click_frequency
        return frequency is None or (
            frequency.count_10s <= _MAX_TOUCHES_10S
            and frequency.count_30s <= _MAX_TOUCHES_30S
        )


@dataclass(frozen=True, slots=True)
class TouchReaction:
    """一次可用触摸反应的预制音频引用和目标表情。"""

    audio_ref: d.MediaRef
    expression_id: str


class TouchReactionSkill:
    """复用旧 builder 的概率、音频筛选与表情映射。"""

    def __init__(self, config: Mapping[str, object]) -> None:
        """用角色 touch.fast_reply 配置构造旧选择器。"""
        manifest = config.get("manifest")
        if manifest is None and config.get("touch_voice_dir") is not None:
            raise ValueError("touch fast reply requires manifest-backed resources")
        if manifest is not None and not isinstance(manifest, (str, Path)):
            raise ValueError("touch fast reply manifest must be a path")
        self._builder = TouchFastReplyBuilder(config)
        self._media_ids = ({entry.audio_path: entry.name for entry in load_prepared_speech(manifest)}
                           if manifest is not None else {})

    def choose(self, stimulus: d.TouchInteraction) -> TouchReaction | None:
        """返回可读取的随机触摸资源；未命中或资源失败时返回 None。"""
        if not self._builder.should_use_fast_path():
            get_logger(__name__).error("Touch fast path missed")
            return None
        audio_path = self._builder._pick_audio_file()
        if audio_path is None:
            return None
        try:
            Path(audio_path).read_bytes()
        except OSError:
            get_logger(__name__).exception("Touch voice read failed path=%s", audio_path)
            return None
        expression_id = self._builder._expression_for(audio_path) or "normal"
        return TouchReaction(
            audio_ref=d.MediaRef(media_id=self._media_ids[audio_path]),
            expression_id=expression_id,
        )
