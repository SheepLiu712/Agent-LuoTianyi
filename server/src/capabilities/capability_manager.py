from __future__ import annotations
from typing import Any, Dict, TYPE_CHECKING
from dataclasses import dataclass

from src.capabilities.singing import SingingCapability
from src.capabilities.speech import SpeechCapability
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.utils.llm_service import LLMService


class CapabilityManager:
    """Container for action capabilities exposed to agents and workers."""
    def __init__(self, config: Dict, llm_service: LLMService):
        self._config: Dict[str, Any] = config
        self.llm_service: LLMService = llm_service
        self.logger = get_logger(__name__)

        self.logger.info("Start initializing Speech Capability...")
        self.speech: SpeechCapability = SpeechCapability(self._config.get("tts", {}))
        self.logger.info("Start initializing Singing Capability...")
        self.singing: SingingCapability = SingingCapability(self._config.get("sing", {}))
