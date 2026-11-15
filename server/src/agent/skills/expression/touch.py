"""触摸预制反应的资源选择技能。"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import src.domain.agent as d
from src.agent.skills.contracts import SkillInvocation
from src.agent.skills.expression._touch_resources import TouchFastReplyBuilder
from src.agent.skills.expression.prepared_speech import PreparedSpeechCatalog
from src.utils.logger import get_logger


@dataclass(frozen=True, slots=True)
class TouchReaction:
    """一次可用触摸反应的预制音频引用和目标表情。"""

    audio_ref: d.MediaRef
    expression_id: str


class TouchReactionSkill:
    """共享所有角色的触摸预制资源选择器；部位契约在输入边界校验。"""

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
    ) -> tuple[TouchFastReplyBuilder, dict[object, str]]:
        try:
            entries = prepared_speech.entries(character_id)
        except KeyError:
            raise ValueError(f"touch fast reply requires prepared speech catalog for {character_id}") from None
        builder = TouchFastReplyBuilder(config, entries)
        media_ids = {entry.audio_path: entry.name for entry in entries}
        return builder, media_ids

    def choose(self, invocation: SkillInvocation, stimulus: d.TouchInteraction) -> TouchReaction | None:
        """返回可读取的随机触摸资源；未命中或资源失败时返回 None。"""
        resources = self._resources.get(invocation.character_id)
        if resources is None:
            return None
        builder, media_ids = resources
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
