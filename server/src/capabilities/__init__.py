"""Agent-callable capabilities.

Capabilities execute actions such as speaking or singing. They do not decide
when an action should happen; that belongs to the agent layer.
"""

from src.capabilities.capability_manager import CapabilityManager
from src.capabilities.singing import SingingCapability
from src.capabilities.speech import SpeechCapability, TTSModule, TTSServer, init_tts_module

__all__ = [
    "CapabilityRegistry",
    "SingingCapability",
    "SpeechCapability",
    "TTSModule",
    "TTSServer",
    "init_tts_module",
]
