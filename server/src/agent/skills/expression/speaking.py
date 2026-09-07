"""按角色、文本和语调流式生成语音。"""

from contextlib import aclosing
from dataclasses import dataclass
from collections.abc import AsyncIterator
from typing import Any

from src.capabilities.speech.streaming import AsyncTTS
from src.domain.agent import AudioFraming, CancellationToken, Tone


@dataclass(frozen=True)
class _SpeakingConfig:
    """当前无独立行为参数，仅验证本层配置容器。"""

    @classmethod
    def from_dict(cls, config: dict[str, Any]) -> "_SpeakingConfig":
        if not isinstance(config, dict):
            raise TypeError("speaking 必须是字典")
        return cls()


@dataclass(frozen=True)
class SpeakingAudioChunk:
    """一个编码音频片段；framing 表示是否需要与其他片段拼接。"""

    data: bytes
    framing: AudioFraming


class EmptySpeechError(Exception):
    """TTS 正常结束，但没有产生任何有效音频。"""


class SpeakingSkill:
    """角色共享的语音生成技能，不处理表情、输出身份或消息终止。"""

    def __init__(self, config: dict[str, Any], tts_engine: AsyncTTS) -> None:
        """校验本层 config 并绑定已初始化的 tts_engine。"""
        self._config = _SpeakingConfig.from_dict(config)
        self._tts = tts_engine

    async def speak(self, *, character_id: str, text: str, tone: Tone,
                    cancellation: CancellationToken) -> AsyncIterator[SpeakingAudioChunk]:
        """按角色、朗读文本和语调生成音频；取消时释放本次流，空音频抛 EmptySpeechError。

        调用方提前停止消费时须关闭生成器；可使用 contextlib.aclosing。
        """
        if not isinstance(character_id, str) or not character_id.strip():
            raise ValueError("character_id 不能为空")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("朗读文本不能为空")
        if not isinstance(tone, Tone) or not isinstance(cancellation, CancellationToken):
            raise TypeError("tone 和 cancellation 必须使用领域类型")
        generated = False
        async with aclosing(self._tts.stream(character_id=character_id, text=text, tone=tone.value,
                                             cancellation=cancellation)) as stream:
            async for data in stream:
                generated = True
                yield SpeakingAudioChunk(data, AudioFraming.FILE_FRAGMENT)
        if not generated:
            raise EmptySpeechError("TTS 未生成有效音频")
