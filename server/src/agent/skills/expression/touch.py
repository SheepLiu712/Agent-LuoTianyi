"""触摸预制反应的资源选择技能。"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import src.domain.agent as d
from src.agent.reflex.touch import TouchFastReplyBuilder
from src.resources.prepared_speech import load_prepared_speech
from src.utils.logger import get_logger


@dataclass(frozen=True, slots=True)
class TouchReaction:
    """一次可用触摸反应的预制音频引用和目标表情。"""

    audio_ref: d.MediaRef
    expression_id: str


class TouchReactionSkill:
    """复用旧 builder 的概率、音频筛选与表情映射。"""

    def __init__(self, config: Mapping[str, object]) -> None:
        """用角色 touch.fast_reply 配置构造旧选择器。"""
        self._builder = TouchFastReplyBuilder(config)
        manifest = config.get("manifest")
        if manifest is not None and not isinstance(manifest, (str, Path)):
            raise TypeError("touch manifest 必须是路径")
        self._media_ids = ({entry.audio_path: entry.name for entry in load_prepared_speech(manifest)}
                           if manifest else {})

    def choose(self) -> TouchReaction | None:
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
            audio_ref=d.MediaRef(media_id=self._media_ids.get(audio_path, audio_path.stem)),
            expression_id=expression_id,
        )
