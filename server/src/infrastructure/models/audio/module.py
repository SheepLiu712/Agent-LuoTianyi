"""音频模型模块：prompt、委托、观测和统一响应信封。"""

from __future__ import annotations

import inspect
from typing import Any

from src.infrastructure.models.audio.interface import AudioModelAPIInterface
from src.infrastructure.models.client_execution import ClientLLMExecutionError, ClientModelExecutor, notify_fallback
from src.infrastructure.models.llm.prompts import PromptTemplate
from src.infrastructure.observability import get_trace_context
from src.utils.logger import get_logger


class AudioModelModule:
    """用音频和 prompt 调用模型，不包含 Agent 业务语义。"""

    def __init__(
        self,
        module_name: str,
        module_config: dict[str, Any],
        prompt_template: PromptTemplate,
        interface: AudioModelAPIInterface,
        client_llm_executor: ClientModelExecutor | None = None,
    ) -> None:
        self.name = module_name
        self.logger = get_logger(f"AudioModelModule:{module_name}")
        self.prompt_template = prompt_template
        self.interface = interface
        audio_config = module_config.get("audio", {})
        self.params = module_config.get("params", audio_config.get("params", {}))
        self.use_json = module_config.get("use_json", audio_config.get("use_json", True))
        self.client_model_type = str(audio_config.get("client_model_type") or "").strip()
        self.client_llm_executor = client_llm_executor

    async def generate_response(self, audio_base64: str, **prompt_values) -> dict[str, Any]:
        prompt = self.prompt_template.render(**prompt_values)
        request_kwargs = dict(self.params or {})
        if self.use_json:
            request_kwargs["response_format"] = {"type": "json_object"}
        response = await self._generate(prompt, audio_base64=audio_base64, request_kwargs=request_kwargs)
        usage = response.get("usage") or {}
        self.logger.debug(
            "Audio model usage - Prompt: %s, Completion: %s, Total: %s | Response time: %ss",
            usage.get("prompt_tokens", 0),
            usage.get("completion_tokens", 0),
            usage.get("total_tokens", 0),
            response.get("response_time_s", "N/A"),
        )
        return response

    async def _generate(
        self,
        prompt: str,
        *,
        audio_base64: str,
        request_kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        delegate_parameters = (
            inspect.signature(self.client_llm_executor.delegate).parameters
            if self.client_llm_executor is not None
            else {}
        )
        supports_audio = "audio_base64" in delegate_parameters or any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in delegate_parameters.values()
        )
        if self.client_model_type and self.client_llm_executor is not None and supports_audio:
            user_id = get_trace_context().get("user_id")
            try:
                response = await self.client_llm_executor.delegate(
                    user_id,
                    module=self.name,
                    model_type=self.client_model_type,
                    model_kind="audio",
                    prompt=prompt,
                    params=self.params,
                    use_json=self.use_json,
                    audio_base64=audio_base64,
                )
            except ClientLLMExecutionError as exc:
                self.logger.warning("Client audio delegation failed for module %s; using server interface", self.name)
                await notify_fallback(self.client_llm_executor, user_id, self.name, exc)
                response = None
            if response is not None:
                return response
        return await self.interface.generate_response(prompt, audio_base64=audio_base64, **request_kwargs)
