"""受控音频解析、结构化理解、重试与降级。"""

from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.agent.context import AudioUnderstandingStatus
from src.domain.agent import MediaRef
from src.infrastructure.media import MediaResolver, ResolvedMedia
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.infrastructure.models.audio.module import AudioModelModule
    from src.infrastructure.models.service import LLMService


@dataclass(frozen=True)
class AudioUnderstandingResult:
    """经过业务校验和规范化的音频理解字段。"""

    transcript: str | None
    emotion: str | None
    sound_description: str | None


class AudioUnderstandingSkill:
    """将 owner-bound 音频转为可安全写入上下文的结构化结果。"""

    def __init__(
        self,
        config: dict[str, Any],
        media_resolver: MediaResolver,
        llm_service: LLMService | None = None,
        *,
        audio_module: AudioModelModule | None = None,
        timeout_seconds: float = 20.0,
        retry_delay_seconds: float = 1.0,
    ) -> None:
        if not isinstance(config, dict):
            raise TypeError("audio_understanding config must be a dictionary")
        if audio_module is None:
            if llm_service is None:
                raise RuntimeError("audio understanding requires LLMService or AudioModelModule")
            audio_module = llm_service.register_audio_model_module(
                "audio_understanding", config.get("audio_model_module", {})
            )
        self._media_resolver = media_resolver
        self._audio_module = audio_module
        self._timeout_seconds = timeout_seconds
        self._retry_delay_seconds = retry_delay_seconds
        self._logger = get_logger(__name__)

    async def understand(
        self,
        media_ref: MediaRef,
        *,
        owner_user_id: str,
    ) -> tuple[ResolvedMedia, AudioUnderstandingStatus, AudioUnderstandingResult]:
        """解析一次媒体；模型失败两次后返回成功降级结果。"""
        media = await asyncio.to_thread(
            self._media_resolver.resolve,
            media_ref,
            owner_user_id=owner_user_id,
            expected_kind="audio",
        )
        encoded = base64.b64encode(media.data).decode("ascii")
        data_uri = f"data:{media.mime_type};base64,{encoded}"
        for attempt in range(2):
            try:
                response = await asyncio.wait_for(
                    self._audio_module.generate_response(audio_base64=data_uri),
                    timeout=self._timeout_seconds,
                )
                return media, AudioUnderstandingStatus.UNDERSTOOD, self._parse(response)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                # 只记录失败事实与异常类型；禁止记录音频、Base64、转写或描述内容。
                self._logger.warning(
                    "audio understanding attempt failed media_id=%s attempt=%s error=%s",
                    media_ref.media_id,
                    attempt + 1,
                    type(error).__name__,
                )
                if attempt == 0:
                    await asyncio.sleep(self._retry_delay_seconds)
        self._logger.warning("audio understanding degraded to NOT_UNDERSTOOD media_id=%s", media_ref.media_id)
        return media, AudioUnderstandingStatus.NOT_UNDERSTOOD, AudioUnderstandingResult(None, None, None)

    @staticmethod
    def _parse(response: Any) -> AudioUnderstandingResult:
        content = response.get("content") if isinstance(response, dict) else None
        if not isinstance(content, str):
            raise ValueError("audio model response content must be a string")
        payload = json.loads(content)
        required = {"transcript", "emotion", "sound_description"}
        if not isinstance(payload, dict) or set(payload) != required:
            raise ValueError("audio model response must contain exactly three required keys")
        values = {key: AudioUnderstandingSkill._clean(payload[key]) for key in required}
        if values["transcript"] is None and values["sound_description"] is None:
            raise ValueError("audio response contains no transcript or sound description")
        if values["transcript"] is None and values["emotion"] is not None:
            raise ValueError("emotion requires transcript")
        return AudioUnderstandingResult(
            transcript=values["transcript"],
            emotion=values["emotion"],
            sound_description=values["sound_description"],
        )

    @staticmethod
    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise TypeError("audio understanding values must be strings or null")
        return value.strip() or None
