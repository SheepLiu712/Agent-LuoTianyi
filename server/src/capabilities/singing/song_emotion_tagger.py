from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING

from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.utils.llm.llm_module import LLMModule
    from src.utils.llm_service import LLMService


SONG_EMOTION_TAGS = ("甜美", "温柔", "积极", "帅气", "搞怪", "伤感", "愤怒")


class SongEmotionTagger:
    """Uses one registered LLM module for song and context emotion labels."""

    def __init__(self, logger=None) -> None:
        self.logger = logger or get_logger(__name__)
        self.llm: "LLMModule | None" = None

    def register(self, llm_service: "LLMService", module_config: dict[str, Any]) -> None:
        self.llm = llm_service.register_llm_module("song_emotion_tagger", module_config)

    @property
    def available(self) -> bool:
        return self.llm is not None

    async def tag_song(self, song_name: str, lyrics: str) -> list[str]:
        return await self._generate("tag_song", song_name, lyrics)

    async def infer_target_tags(self, context: str) -> list[str]:
        return await self._generate("infer_target", "", context)

    async def _generate(self, mode: str, song_name: str, content: str) -> list[str]:
        if self.llm is None:
            self.logger.warning("Song emotion tagger LLM module is unavailable")
            return []
        try:
            response = await self.llm.generate_response(
                mode=mode,
                song_name=song_name or "无",
                content=content or "无",
            )
            return self.parse_tags(response)
        except Exception as exc:
            self.logger.warning(f"Song emotion tagging failed: {exc}")
            return []

    @staticmethod
    def parse_tags(response: str | dict[str, Any] | None) -> list[str]:
        if isinstance(response, dict):
            payload = response
        else:
            text = str(response or "").strip()
            if "```" in text:
                text = text.replace("```json", "").replace("```", "").strip()
            try:
                payload = json.loads(text)
            except (TypeError, json.JSONDecodeError):
                return []

        if not isinstance(payload, dict):
            return []
        raw_tags = payload.get("emotion_tags") or payload.get("target_emotion_tags") or []
        if isinstance(raw_tags, str):
            raw_tags = [raw_tags]
        if not isinstance(raw_tags, list):
            return []

        result: list[str] = []
        allowed = set(SONG_EMOTION_TAGS)
        for tag in raw_tags:
            normalized = str(tag).strip()
            if normalized in allowed and normalized not in result:
                result.append(normalized)
        return result
