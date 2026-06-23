from __future__ import annotations

from typing import Generator, Dict

from src.capabilities.speech.tts_module import TTSModule, init_tts_module


class SpeechCapability:
    """Action capability for saying text through TTS."""

    def __init__(self, config: Dict) -> None:
        self._tts_config = config
        self.tts_module = init_tts_module(self._tts_config)

    async def say(self, text: str, tone: str) -> str:
        audio_bytes = await self.tts_module.synthesize_speech_with_tone(text, tone)
        return self.tts_module.encode_audio_to_base64(audio_bytes)

    def say_stream(self, text: str, tone: str) -> Generator[str, None, None]:
        for chunk in self.tts_module.stream_synthesize_speech_with_tone(text, tone):
            yield self.tts_module.encode_audio_to_base64(chunk)
