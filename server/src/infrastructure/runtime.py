from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Dict

from src.infrastructure.image_understanding import ImageUnderstanding
from src.infrastructure.media import (
    FilesystemMediaResolver,
    UnconfiguredMediaResolver,
)
from src.infrastructure.singing import SingingBackend
from src.infrastructure.speech import SpeechBackend
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.utils.llm_service import LLMService


class InfrastructureRuntime:
    """Shared external adapters, model resources, and their lifecycle."""

    def __init__(self, config: Dict, llm_service: LLMService):
        self.config: Dict[str, Any] = config
        self.logger = get_logger(__name__)
        self.llm_service: "LLMService | None" = llm_service
        self._stop_lock = asyncio.Lock()
        self._stopped = False

        try:
            self.logger.info("Start initializing speech backend...")
            self.speech: SpeechBackend = SpeechBackend(self.config.get("tts", {}))

            self.logger.info("Start initializing singing backend...")
            self.singing: SingingBackend = SingingBackend(
                self.config.get("sing", {}),
                llm_service=llm_service,
            )

            self.logger.info("Start initializing image understanding adapter...")
            self.image_understanding: ImageUnderstanding = ImageUnderstanding(
                self.config.get("image_understanding", {})
            )
            self.image_understanding.create_vlm_module(llm_service)

            self.logger.info("Start initializing media resolver...")
            media_config = self.config.get("media_resolution", {})
            self.media_resolver = (
                FilesystemMediaResolver(media_config)
                if isinstance(media_config, dict) and media_config.get("root")
                else UnconfiguredMediaResolver(media_config)
            )
        except BaseException:
            speech = getattr(self, "speech", None)
            if speech is not None:
                try:
                    speech._abort_initialization()
                except Exception as error:
                    self.logger.error(f"Infrastructure initialization rollback failed: {error}")
            raise

    def wire_dependencies(self, *, llm_service: "LLMService | None" = None) -> None:
        """完成基础设施依赖校验。"""
        if llm_service is not None:
            self.llm_service = llm_service
        self.ensure_dependencies()

    def ensure_dependencies(self) -> None:
        """检查全部共享适配器已经初始化。"""
        required = {
            "llm_service": self.llm_service,
            "speech": self.speech,
            "singing": self.singing,
            "image_understanding": self.image_understanding,
            "media_resolver": self.media_resolver,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise RuntimeError(f"InfrastructureRuntime dependencies are missing: {', '.join(missing)}")
        self.speech.ensure_dependencies()
        self.singing.ensure_dependencies()
        self.image_understanding.ensure_dependencies()
        self.media_resolver.ensure_dependencies()

    async def stop(self) -> None:
        """Stop owned resources exactly once after a successful attempt."""
        async with self._stop_lock:
            if self._stopped:
                return
            await self.speech.stop()
            self._stopped = True
