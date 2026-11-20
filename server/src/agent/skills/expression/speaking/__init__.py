"""说话 Skill 及其私有 TTS 实现。"""

from src.agent.skills.expression.speaking.backend import SpeechBackend
from src.agent.skills.expression.speaking.call_pcm import UnsupportedCallAudioError
from src.agent.skills.expression.speaking.errors import TTSStreamCancelled
from src.agent.skills.expression.speaking.skill import (
    EmptySpeechError,
    SpeakingAudioChunk,
    SpeakingDisabledError,
    SpeakingSkill,
)
from src.agent.skills.expression.speaking.streaming import AsyncTTS
from src.agent.skills.expression.speaking.tts_module import TTSModule, init_tts_module
from src.agent.skills.expression.speaking.tts_server import TTSServer

__all__ = [
    "AsyncTTS",
    "EmptySpeechError",
    "SpeakingAudioChunk",
    "SpeakingDisabledError",
    "SpeakingSkill",
    "SpeechBackend",
    "TTSModule",
    "TTSServer",
    "TTSStreamCancelled",
    "UnsupportedCallAudioError",
    "init_tts_module",
]
