from __future__ import annotations

import base64
import json
import random
from pathlib import Path
from typing import Awaitable, Callable, Mapping
from uuid import uuid4

from src.system.user_interface.types import ChatResponse
from src.agent.chat.chat_events import ChatInputEvent, ChatInputEventType
from src.utils.logger import get_logger


logger = get_logger("TouchReflex")

TOUCH_FAST_REPLY_PROBABILITY = 1.0
_AUDIO_SUFFIXES = {".wav", ".mp3", ".ogg", ".m4a", ".flac"}


class TouchFastReplyBuilder:
    """Builds transient Live2D touch replies from pre-recorded voice clips."""

    def __init__(self, touch_voice_dir: Path | None = None, probability: float = TOUCH_FAST_REPLY_PROBABILITY):
        server_root = Path(__file__).resolve().parents[2]
        self.touch_voice_dir = touch_voice_dir or server_root / "res" / "agent" / "touch_voice"
        self.probability = probability
        self._voice_to_expression: dict[str, str] | None = None

    def should_use_fast_path(self) -> bool:
        return random.random() < self.probability

    def build_response(self) -> ChatResponse | list[ChatResponse] | None:
        audio_path = self._pick_audio_file()
        if audio_path is None:
            return None

        try:
            audio_base64 = base64.b64encode(audio_path.read_bytes()).decode("utf-8")
        except Exception as exc:
            logger.warning(f"Failed to read touch voice {audio_path}: {exc}")
            return None

        expression = self._expression_for(audio_path)
        response = ChatResponse(
            uuid=f"touch-{uuid4().hex}",
            text="",
            audio=audio_base64,
            expression=expression,
            is_final_package=True,
            display_in_chat=False,
            is_ephemeral=True,
        )
        if expression == "normal":
            return response
        return [
            response,
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
        return mapping.get(audio_path.stem) or mapping.get(audio_path.name) or "normal"

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


class TouchReflexResponder:
    """Handles touch as an ephemeral reflex before it becomes a topic."""

    def __init__(self, builder: TouchFastReplyBuilder | None = None):
        self.builder = builder or TouchFastReplyBuilder()

    async def try_reply(
        self,
        event: ChatInputEvent,
        send_reply_callback: Callable[[ChatResponse], Awaitable[None]],
    ) -> bool:
        if event.event_type != ChatInputEventType.USER_TOUCH:
            return False
        if not self.builder.should_use_fast_path():
            return False

        response = self.builder.build_response()
        if response is None:
            logger.warning("Touch reflex unavailable; falling back to topic pipeline")
            return False

        if isinstance(response, ChatResponse):
            await send_reply_callback(response)
        else:
            for item in response:
                await send_reply_callback(item)
        logger.info("Touch event resolved by ephemeral reflex response")
        return True
