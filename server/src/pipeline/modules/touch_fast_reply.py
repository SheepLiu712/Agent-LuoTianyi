import base64
import json
import random
from pathlib import Path
from typing import Mapping
from uuid import uuid4

from ...interface.types import ChatResponse
from ...utils.logger import get_logger


logger = get_logger("TouchFastReply")

TOUCH_FAST_REPLY_PROBABILITY = 1.0  
_AUDIO_SUFFIXES = {".wav", ".mp3", ".ogg", ".m4a", ".flac"}


class TouchFastReplyBuilder:
    """Builds transient Live2D touch replies from pre-recorded voice clips."""

    def __init__(self, touch_voice_dir: Path | None = None, probability: float = TOUCH_FAST_REPLY_PROBABILITY):
        server_root = Path(__file__).resolve().parents[3]
        self.touch_voice_dir = touch_voice_dir or server_root / "res" / "agent" / "touch_voice"
        self.probability = probability
        self._voice_to_expression: dict[str, str] | None = None

    def should_use_fast_path(self) -> bool:
        return random.random() < self.probability

    def build_response(self) -> ChatResponse | None:
        audio_path = self._pick_audio_file()
        if audio_path is None:
            return None

        try:
            audio_base64 = base64.b64encode(audio_path.read_bytes()).decode("utf-8")
        except Exception as exc:
            logger.warning(f"Failed to read touch voice {audio_path}: {exc}")
            return None

        expression = self._expression_for(audio_path)
        if expression == "normal":
            return ChatResponse(
                uuid=f"touch-{uuid4().hex}",
                text="",
                audio=audio_base64,
                expression=expression,
                is_final_package=True,
                display_in_chat=False,
                is_ephemeral=True,
            )
        else:
            # If the expression is not "normal", we need one more response to reset the expression back to "normal"
            return [
                ChatResponse(
                    uuid=f"touch-{uuid4().hex}",
                    text="",
                    audio=audio_base64,
                    expression=expression,
                    is_final_package=True,
                    display_in_chat=False,
                    is_ephemeral=True,
                ),
                ChatResponse(
                    uuid=f"touch-{uuid4().hex}",
                    text="",
                    audio="",
                    expression="normal",
                    is_final_package=True,
                    display_in_chat=False,
                    is_ephemeral=True,
                ),
            ]

    def _pick_audio_file(self) -> Path | None:
        if not self.touch_voice_dir.exists():
            logger.warning(f"Touch voice directory not found: {self.touch_voice_dir}")
            return None

        files = [
            path
            for path in self.touch_voice_dir.iterdir()
            if path.is_file() and path.suffix.lower() in _AUDIO_SUFFIXES
        ]
        if not files:
            logger.warning(f"No touch voice audio files found in {self.touch_voice_dir}")
            return None
        return random.choice(files)

    def _expression_for(self, audio_path: Path) -> str | None:
        mapping = self._load_voice_to_expression()
        return mapping.get(audio_path.stem) or mapping.get(audio_path.name)

    def _load_voice_to_expression(self) -> Mapping[str, str]:
        if self._voice_to_expression is not None:
            return self._voice_to_expression

        mapping_path = self.touch_voice_dir / "voice_to_expression.json"
        try:
            raw = json.loads(mapping_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._voice_to_expression = {
                    str(key): str(value)
                    for key, value in raw.items()
                    if str(key).strip() and str(value).strip()
                }
            else:
                self._voice_to_expression = {}
        except FileNotFoundError:
            logger.warning(f"Touch voice expression mapping not found: {mapping_path}")
            self._voice_to_expression = {}
        except Exception as exc:
            logger.warning(f"Failed to load touch voice expression mapping {mapping_path}: {exc}")
            self._voice_to_expression = {}
        return self._voice_to_expression
