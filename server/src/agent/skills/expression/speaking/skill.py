"""按角色、文本和语调流式生成语音。"""

from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass
from typing import Any

from src.agent.skills.contracts import SkillInvocation
from src.agent.skills.expression.speaking.backend import SpeechBackend
from src.agent.skills.expression.speaking.streaming import AsyncTTS
from src.domain.agent import AudioFraming, Tone


@dataclass(frozen=True)
class _SpeakingConfig:
    """说话 Skill 的角色 TTS 配置。"""

    characters: dict[str, dict[str, Any]]

    @classmethod
    def from_dict(cls, config: dict[str, Any]) -> "_SpeakingConfig":
        if not isinstance(config, dict):
            raise TypeError("speaking 必须是字典")
        characters = config.get("characters", {})
        if not isinstance(characters, dict):
            raise TypeError("speaking.characters 必须是字典")
        return cls(characters)


@dataclass(frozen=True)
class SpeakingAudioChunk:
    """一个编码音频片段；framing 表示是否需要与其他片段拼接。"""

    data: bytes
    framing: AudioFraming


class EmptySpeechError(Exception):
    """TTS 正常结束，但没有产生任何有效音频。"""


class SpeakingSkill:
    """角色共享的语音生成技能，不处理表情、输出身份或消息终止。"""

    def __init__(self, config: dict[str, Any], tts_engine: AsyncTTS | None = None) -> None:
        """构造角色 TTS worker；测试可注入已初始化的 tts_engine。"""
        self._config = _SpeakingConfig.from_dict(config)
        self._backend = None if tts_engine is not None else SpeechBackend(self._config.characters)
        self._tts = tts_engine or AsyncTTS(self._backend)

    async def stop(self) -> None:
        """停止该 Skill 拥有的所有共享 TTS worker。"""
        if self._backend is not None:
            await self._backend.stop()

    def abort_initialization(self) -> None:
        """初始化后续 Skill 失败时同步回收已启动的 worker。"""
        if self._backend is not None:
            self._backend._abort_initialization()

    async def speak(self, invocation: SkillInvocation, *, text: str, tone: Tone) -> AsyncIterator[SpeakingAudioChunk]:
        """按角色、朗读文本和语调生成音频；取消时释放本次流，空音频抛 EmptySpeechError。

        调用方提前停止消费时须关闭生成器；可使用 contextlib.aclosing。
        """
        if not isinstance(text, str) or not text.strip():
            raise ValueError("朗读文本不能为空")
        if not isinstance(tone, Tone):
            raise TypeError("tone 必须使用领域类型")
        generated = False
        async with aclosing(
            self._tts.stream(
                character_id=invocation.character_id,
                text=text,
                tone=tone.value,
                cancellation=invocation.cancellation,
            )
        ) as stream:
            async for data in stream:
                generated = True
                yield SpeakingAudioChunk(data, AudioFraming.FILE_FRAGMENT)
        if not generated:
            raise EmptySpeechError("TTS 未生成有效音频")
