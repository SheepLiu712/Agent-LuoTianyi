"""触摸技能私有的预制资源选择实现。"""

from __future__ import annotations

import json
import random
from collections.abc import Mapping
from pathlib import Path

from src.resources.prepared_speech import load_prepared_speech
from src.utils.logger import get_logger

logger = get_logger(__name__)
TOUCH_FAST_REPLY_PROBABILITY = 1.0
_AUDIO_SUFFIXES = {".wav", ".mp3", ".ogg", ".m4a", ".flac"}


class TouchFastReplyBuilder:
    """根据角色档案中的触摸资源选择音频与表情。"""

    def __init__(self, config: Mapping):
        self.config = dict(config or {})
        configured_dir = self.config.get("touch_voice_dir")
        self.touch_voice_dir = Path(configured_dir) if configured_dir else None
        self.probability = float(self.config.get("probability", TOUCH_FAST_REPLY_PROBABILITY))
        self._voice_to_expression: dict[str, str] | None = None
        self._prepared_expressions: dict[Path, str] | None = None
        if self.config.get("manifest"):
            catalog = {entry.name: entry for entry in load_prepared_speech(self.config["manifest"])}
            selected = [catalog[name] for name in self.config["resource_names"]]
            if not selected or any(entry.text for entry in selected):
                raise ValueError("触摸语音必须选择无文字的预制资源")
            self._prepared_expressions = {entry.audio_path: entry.expression for entry in selected}

    def should_use_fast_path(self) -> bool:
        return random.random() < self.probability

    def pick_audio_file(self) -> Path | None:
        if self._prepared_expressions is not None:
            return random.choice(tuple(self._prepared_expressions))
        if self.touch_voice_dir is None:
            logger.warning("Touch voice directory is not configured for this character")
            return None
        if not self.touch_voice_dir.exists():
            logger.warning("Touch voice directory not found: %s", self.touch_voice_dir)
            return None
        files = [
            path for path in self.touch_voice_dir.iterdir() if path.is_file() and path.suffix.lower() in _AUDIO_SUFFIXES
        ]
        if not files:
            logger.warning("No touch voice audio files found in %s", self.touch_voice_dir)
            return None
        return random.choice(files)

    def expression_for(self, audio_path: Path) -> str | None:
        if self._prepared_expressions is not None:
            return self._prepared_expressions[audio_path]
        mapping = self._load_voice_to_expression()
        return mapping.get(audio_path.stem) or mapping.get(audio_path.name) or "normal"

    def _load_voice_to_expression(self) -> Mapping[str, str]:
        if self._voice_to_expression is not None:
            return self._voice_to_expression
        if self.touch_voice_dir is None:
            self._voice_to_expression = {}
            return self._voice_to_expression
        mapping_path = self.touch_voice_dir / "voice_to_expression.json"
        try:
            raw = json.loads(mapping_path.read_text(encoding="utf-8"))
            self._voice_to_expression = (
                {str(key): str(value) for key, value in raw.items() if str(key).strip() and str(value).strip()}
                if isinstance(raw, dict)
                else {}
            )
        except FileNotFoundError:
            logger.warning("Touch voice expression mapping not found: %s", mapping_path)
            self._voice_to_expression = {}
        except Exception as exc:  # noqa: BLE001 - 资源映射失败时回落默认表情
            logger.warning("Failed to load touch voice expression mapping %s: %s", mapping_path, exc)
            self._voice_to_expression = {}
        return self._voice_to_expression
