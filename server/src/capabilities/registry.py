from __future__ import annotations

from dataclasses import dataclass

from src.capabilities.singing import SingingCapability
from src.capabilities.speech import SpeechCapability


@dataclass
class CapabilityRegistry:
    """Container for action capabilities exposed to agents and workers."""

    speech: SpeechCapability
    singing: SingingCapability
