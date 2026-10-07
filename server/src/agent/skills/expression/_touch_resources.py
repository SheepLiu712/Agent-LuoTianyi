"""触摸技能私有的预制资源选择实现。"""

from __future__ import annotations

import random
from collections.abc import Mapping
from pathlib import Path

from src.agent.skills.expression.prepared_speech import PreparedSpeech

TOUCH_FAST_REPLY_PROBABILITY = 1.0


class TouchFastReplyBuilder:
    """根据角色档案中的触摸资源选择音频与表情。"""

    def __init__(self, config: Mapping, entries: tuple[PreparedSpeech, ...]):
        self.config = dict(config or {})
        self.probability = float(self.config.get("probability", TOUCH_FAST_REPLY_PROBABILITY))
        catalog = {entry.name: entry for entry in entries}
        selected = [catalog[name] for name in self.config.get("resource_names", ())]
        if not selected or any(entry.text for entry in selected):
            raise ValueError("触摸语音必须选择无文字的预制资源")
        self._prepared_expressions = {entry.audio_path: entry.expression for entry in selected}

    def should_use_fast_path(self) -> bool:
        return random.random() < self.probability

    def pick_audio_file(self) -> Path | None:
        return random.choice(tuple(self._prepared_expressions))

    def expression_for(self, audio_path: Path) -> str | None:
        return self._prepared_expressions[audio_path]
