from __future__ import annotations

from typing import Generator, Dict

from src.capabilities.speech.tts_module import init_tts_module, TTSModule


class SpeechCapability:
    """Action capability for saying text through TTS."""

    def __init__(self, config: Dict) -> None:
        self.tts_config = config
        self.tts_module: Dict[str, TTSModule] = {}
        for character, tts_config in self.tts_config.items():
            self.tts_module[character] = init_tts_module(tts_config)

    def ensure_dependencies(self) -> None:
        """检查语音能力依赖已经初始化。"""
        if self.tts_config is None:
            raise RuntimeError("SpeechCapability dependency is missing: tts_config")
        if self.tts_module is None:
            raise RuntimeError("SpeechCapability dependency is missing: tts_module")

    async def say(self, character: str, text: str, tone: str) -> str:
        '''
        使用TTS合成语音。

        :param character: 角色名称
        :param text: 要合成的文本
        :param tone: 语音 tone
        :return: Base64编码的音频数据
        '''
        if character not in self.tts_module:
            raise ValueError(f"TTS module for character '{character}' is not initialized.")
        character_tts_module: TTSModule = self.tts_module[character]
        audio_bytes = await character_tts_module.synthesize_speech_with_tone(text, tone)
        return character_tts_module.encode_audio_to_base64(audio_bytes)

    def say_stream(self, character: str, text: str, tone: str) -> Generator[str, None, None]:
        '''
        使用TTS合成语音，采用流式输出方式。

        :param character: 角色名称
        :param text: 要合成的文本
        :param tone: 语音 tone
        :return: 生成器，逐块返回Base64编码的音频数据
        '''
        if character not in self.tts_module:
            raise ValueError(f"TTS module for character '{character}' is not initialized.")
        
        character_tts_module: TTSModule = self.tts_module[character]
        for chunk in character_tts_module.stream_synthesize_speech_with_tone(text, tone):
            yield character_tts_module.encode_audio_to_base64(chunk)
