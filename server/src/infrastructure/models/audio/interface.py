"""OpenAI 兼容的音频模型接口。"""

from __future__ import annotations

import asyncio
import os
import time
from abc import ABC, abstractmethod
from typing import Any

from openai import OpenAI

from src.infrastructure.models.response_parsing import extract_openai_response
from src.utils.logger import get_logger


class AudioModelAPIInterface(ABC):
    """音频模型窄接口。"""

    @abstractmethod
    async def generate_response(self, prompt: str, audio_base64: str, **kwargs) -> dict[str, Any]: ...

    @abstractmethod
    def get_interface_info(self) -> dict[str, Any]: ...


class OpenAIAudioModelAPIInterface(AudioModelAPIInterface):
    """通过 DashScope OpenAI 兼容接口调用 Qwen Omni。"""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.logger = get_logger(__name__)
        self.base_url = config.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        self.api_key = config.get("api_key") or os.environ.get("QWEN_API_KEY") or ""
        self.model = config.get("model", "qwen3.8-omni-flash")
        self.max_tokens = config.get("max_tokens", 2048)
        self.temperature = config.get("temperature", 0.1)
        self.client: OpenAI | None = None

    def _ensure_client(self) -> OpenAI:
        if self.client is not None:
            return self.client
        if not self.api_key:
            raise RuntimeError("服务端未配置音频模型 API Key")
        self.client = OpenAI(base_url=self.base_url, api_key=self.api_key)
        return self.client

    async def generate_response(self, prompt: str, audio_base64: str, **kwargs) -> dict[str, Any]:
        client = self._ensure_client()
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "input_audio", "input_audio": {"data": audio_base64, "format": "mp4"}},
                ],
            }
        ]

        def request():
            return client.chat.completions.create(
                messages=messages,
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                **kwargs,
            )

        started = time.perf_counter()
        response = await asyncio.to_thread(request)
        return extract_openai_response(
            response,
            elapsed=time.perf_counter() - started,
            logger=self.logger,
            log_usage=True,
        )

    def get_interface_info(self) -> dict[str, Any]:
        return {"type": type(self).__name__, "model": self.model, "base_url": self.base_url}


class AudioModelAPIFactory:
    """创建音频模型接口。"""

    @staticmethod
    def create_interface(config: dict[str, Any]) -> AudioModelAPIInterface:
        api_type = str(config.get("api_type", "openai")).lower()
        if api_type != "openai":
            raise ValueError(f"未知的音频模型 API 类型: {api_type}")
        return OpenAIAudioModelAPIInterface(config)
