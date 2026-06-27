from __future__ import annotations
from typing import Any, Dict, TYPE_CHECKING
from dataclasses import dataclass

from src.capabilities.singing import SingingCapability
from src.capabilities.speech import SpeechCapability
from src.capabilities.image_understanding import ImageUnderstanding
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.utils.llm_service import LLMService


class CapabilityManager:
    """Container for action capabilities exposed to agents and workers."""
    def __init__(self, config: Dict, llm_service: LLMService):
        self.config: Dict[str, Any] = config
        self.logger = get_logger(__name__)
        self.llm_service: "LLMService | None" = llm_service

        # TTS合成能力
        self.logger.info("Start initializing Speech Capability...")
        self.speech: SpeechCapability = SpeechCapability(self.config.get("tts", {}))

        # 歌唱能力
        self.logger.info("Start initializing Singing Capability...")
        self.singing: SingingCapability = SingingCapability(self.config.get("sing", {}))

        # 图像理解能力
        self.logger.info("Start initializing Image Understanding Capability...")
        self.image_understanding: ImageUnderstanding = ImageUnderstanding(self.config.get("image_understanding", {}))
        self.image_understanding.create_vlm_module(llm_service)

    def wire_dependencies(self, *, llm_service: "LLMService") -> None:
        """向能力子模块派发外部依赖。"""
        self.llm_service = llm_service
        self.image_understanding.create_vlm_module(llm_service)
        self.ensure_dependencies()

    def ensure_dependencies(self) -> None:
        """检查能力管理器和各能力子模块已经初始化。"""
        required = {
            "llm_service": self.llm_service,
            "speech": self.speech,
            "singing": self.singing,
            "image_understanding": self.image_understanding,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise RuntimeError(f"CapabilityManager dependencies are missing: {', '.join(missing)}")
        self.speech.ensure_dependencies()
        self.singing.ensure_dependencies()
        self.image_understanding.ensure_dependencies()
