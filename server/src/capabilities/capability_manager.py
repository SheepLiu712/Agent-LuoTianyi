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
        self.llm_service: LLMService = llm_service
        self.logger = get_logger(__name__)

        # TTS合成能力
        self.logger.info("Start initializing Speech Capability...")
        self.speech: SpeechCapability = SpeechCapability(self.config.get("tts", {}))

        # 歌唱能力
        self.logger.info("Start initializing Singing Capability...")
        self.singing: SingingCapability = SingingCapability(self.config.get("sing", {}))

        # 图像理解能力
        self.logger.info("Start initializing Image Understanding Capability...")
        self.image_understanding: ImageUnderstanding = ImageUnderstanding(self.config.get("image_understanding", {}))
        self.image_understanding.create_vlm_module(self.llm_service)