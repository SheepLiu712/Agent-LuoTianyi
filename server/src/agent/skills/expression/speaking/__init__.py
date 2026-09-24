"""说话 Skill 及其私有 TTS 实现。"""

from src.agent.skills.expression.speaking.backend import SpeechBackend
from src.agent.skills.expression.speaking.errors import TTSStreamCancelled
from src.agent.skills.expression.speaking.skill import EmptySpeechError, SpeakingAudioChunk, SpeakingSkill
from src.agent.skills.expression.speaking.streaming import AsyncTTS
from src.agent.skills.expression.speaking.tts_module import TTSModule, init_tts_module
from src.agent.skills.expression.speaking.tts_server import TTSServer

__all__ = [
    "AsyncTTS",
    "EmptySpeechError",
    "SpeakingAudioChunk",
    "SpeakingSkill",
    "SpeechBackend",
    "TTSModule",
    "TTSServer",
    "TTSStreamCancelled",
    "init_tts_module",
]
