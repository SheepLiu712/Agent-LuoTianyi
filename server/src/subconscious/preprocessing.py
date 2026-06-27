from __future__ import annotations

from typing import TYPE_CHECKING

from src.domain.chat import ChatInputEvent, ChatInputEventType
from src.subconscious.music_knowledge.jargon import SongEntityLinker
from src.utils.logger import get_logger
from src.utils.vision.image_process import get_image_bytes_from_base64, get_postfix_by_mime, save_image

if TYPE_CHECKING:
    from src.capabilities import CapabilityManager


class ChatPreprocessor:
    """Subconscious preprocessing for incoming chat stimuli."""

    def __init__(self, config: dict, capability_manager: "CapabilityManager") -> None:
        self.config = config
        self.logger = get_logger("ChatPreprocessor")
        self.capability_manager = capability_manager
        self.song_entity_linker = SongEntityLinker(config.get("song_entity_linker", {}))

    def ensure_dependencies(self) -> None:
        """检查聊天预处理器依赖已经初始化。"""
        required = {
            "capability_manager": self.capability_manager,
            "song_entity_linker": self.song_entity_linker,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise RuntimeError(f"ChatPreprocessor dependencies are missing: {', '.join(missing)}")

    async def preprocess_chat_event(
        self,
        character_id: str,
        user_id: str,
        event: ChatInputEvent,
    ) -> ChatInputEvent:
        _ = character_id  # Currently unused, but may be used in future for character-specific preprocessing
        if event.event_type == ChatInputEventType.USER_IMAGE:
            await self._process_image_message( user_id, event)

        song_entities = self.song_entity_linker.extract_and_verify(event.text)
        if song_entities:
            self.logger.debug(f"Extracted song entities from user input: {song_entities}")
            event.payload["terms"] = song_entities
        return event

    async def _process_image_message(
        self,
        user_id: str,
        event: ChatInputEvent,
    ) -> None:
        payload = event.payload
        image_base64 = payload.get("image_base64")
        mime_type = payload.get("mime_type")
        if not image_base64 or not mime_type:
            self.logger.warning(f"Image message from {user_id} is missing image_base64 or mime_type")
            return

        image_bytes = get_image_bytes_from_base64(image_base64)
        if not image_bytes:
            self.logger.error(f"Failed to decode image bytes from base64 for {user_id}")
            return

        postfix = get_postfix_by_mime(mime_type)
        payload["image_server_path"] = save_image(user_id, image_bytes, postfix)

        image_with_header = self._ensure_data_uri_header(image_base64, postfix)
        event.text = await self.capability_manager.image_understanding.describe_image(image_with_header)

    def _ensure_data_uri_header(self, image_base64: str, postfix: str) -> str:
        if not image_base64 or image_base64.startswith("data:image/"):
            return image_base64

        postfix_to_mime = {
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "webp": "image/webp",
            "gif": "image/gif",
            "bmp": "image/bmp",
        }
        mime = postfix_to_mime.get((postfix or "").lower(), "image/jpeg")
        return f"data:{mime};base64,{image_base64}"
