from __future__ import annotations

import base64
import json
import random
from pathlib import Path
from typing import Awaitable, Callable, Mapping, TYPE_CHECKING
from uuid import uuid4

from src.domain.chat import ChatInputEvent, ChatInputEventType
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.system.user_interface.types import ChatResponse


logger = get_logger("TouchReflex")

TOUCH_FAST_REPLY_PROBABILITY = 1.0
_AUDIO_SUFFIXES = {".wav", ".mp3", ".ogg", ".m4a", ".flac"}


class TouchFastReplyBuilder:
    """根据角色档案中的触摸语音资源构造一次性快速回复。"""

    def __init__(self, config: Mapping):
        self.config = dict(config or {})
        configured_dir = self.config.get("touch_voice_dir")
        self.touch_voice_dir = Path(configured_dir) if configured_dir else None
        self.probability = float(self.config.get("probability", TOUCH_FAST_REPLY_PROBABILITY))
        self._voice_to_expression: dict[str, str] | None = None

    def ensure_dependencies(self) -> None:
        """检查触摸快速回复资源已经按角色配置。"""
        if self.touch_voice_dir is None:
            raise RuntimeError("TouchFastReplyBuilder dependency is missing: touch_voice_dir")

    def should_use_fast_path(self) -> bool:
        return random.random() < self.probability

    def build_response(self) -> ChatResponse | list[ChatResponse] | None:
        from src.system.user_interface.types import ChatResponse

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
        if self.touch_voice_dir is None:
            logger.warning("Touch voice directory is not configured for this character")
            return None
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
        if self.touch_voice_dir is None:
            self._voice_to_expression = {}
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
    """处理用户触摸这类低延迟、无需进入话题队列的反射。"""

    def __init__(self, config: Mapping, builder: TouchFastReplyBuilder | None = None):
        self.config = dict(config or {})
        self.builder = builder or TouchFastReplyBuilder(self.config.get("fast_reply", {}))

    def ensure_dependencies(self) -> None:
        """检查触摸反射依赖已经初始化。"""
        if self.builder is None:
            raise RuntimeError("TouchReflexResponder dependency is missing: builder")
        self.builder.ensure_dependencies()

    async def try_reply(
        self,
        event: ChatInputEvent,
        send_reply_callback: Callable[[ChatResponse], Awaitable[None]],
    ) -> bool:
        from src.system.user_interface.types import ChatResponse

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
