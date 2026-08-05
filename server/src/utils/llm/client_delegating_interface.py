"""
ClientDelegatingLLMInterface / ClientDelegatingVLMInterface
----------------------------------------------------------
包装原始 LLM/VLM 接口：当当前用户启用了客户端执行模式且在线连接可用时，
把本次调用转发给客户端执行（客户端使用用户自己的 api-key）；
否则或转发失败时，回退到内部接口（服务端自带 key）。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from src.system.observability import get_trace_context
from src.utils.llm.client_llm_executor import (
    RETRYABLE_EXCEPTIONS,
    ClientLLMExecutor,
    ClientLLMError,
    _looks_like_key_error,
    _looks_like_network_error,
)
from src.utils.llm.llm_api_interface import LLMAPIInterface
from src.utils.logger import get_logger
from src.utils.vision.vlm_api_interface import VLMAPIInterface


CLIENT_RETRY_TIMES = 2
CLIENT_RETRY_INITIAL_DELAY = 1.0

KEY_ERROR_MESSAGE = (
    "你的 LLM API Key 或账户存在问题（无效/未授权/欠费等），本次回复未生成。"
    "请在「LLM 模型设置」重新配置；如需使用服务端 key，请清空后重试。"
)
CLIENT_JSON_UNSUPPORTED_MARKER = "client_model_does_not_support_json"
CLIENT_ERROR_MESSAGE = (
    "客户端 LLM 调用失败，本次回复未生成。请检查网络后重试；"
    "如需使用服务端 key，请在「LLM 模型设置」清空配置。"
)


def _provider_info_from_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """从接口配置中提取客户端调用所需的非敏感信息（不含 api_key）。"""
    config = config or {}
    api_type = str(config.get("api_type", "openai")).lower()
    model = config.get("model", "")
    if api_type == "requests":
        url = config.get("url", "")
    else:
        base_url = str(config.get("base_url", "")).rstrip("/")
        url = f"{base_url}/chat/completions" if base_url else ""
    return {
        "api_type": api_type,
        "url": url,
        "model": model,
    }


def _looks_like_json_unsupported(text: str) -> bool:
    """客户端模型不支持 JSON 输出时，客户端会返回该标记错误。"""
    return CLIENT_JSON_UNSUPPORTED_MARKER in (text or "").lower()


async def _client_request_with_retry(
    executor: ClientLLMExecutor,
    user_id: str,
    *,
    retries: Optional[int] = None,
    initial_delay: Optional[float] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """客户端执行并处理重试：网络类错误重试，key 类错误不重试。"""
    if retries is None:
        retries = CLIENT_RETRY_TIMES
    if initial_delay is None:
        initial_delay = CLIENT_RETRY_INITIAL_DELAY
    last_exc: Optional[Exception] = None
    delay = initial_delay
    for attempt in range(retries + 1):
        try:
            return await executor.request(user_id, **kwargs)
        except ClientLLMError as exc:
            # key 类错误或其他非网络错误不重试
            if _looks_like_key_error(str(exc)) or not _looks_like_network_error(str(exc)):
                raise
            last_exc = exc
            if attempt < retries:
                await asyncio.sleep(delay)
                delay *= 2
        except RETRYABLE_EXCEPTIONS as exc:
            last_exc = exc
            if attempt < retries:
                await asyncio.sleep(delay)
                delay *= 2
        except Exception as exc:
            last_exc = exc
            break
    if last_exc is None:
        last_exc = ClientLLMError("client request failed")
    raise last_exc


class ClientDelegatingLLMInterface(LLMAPIInterface):
    """LLM 接口包装：优先由用户客户端执行，失败回退服务端直连。"""

    def __init__(self, inner: LLMAPIInterface, executor: Optional[ClientLLMExecutor]):
        self.inner = inner
        self.executor = executor
        self.logger = get_logger(__name__)
        self.default_parameters = dict(getattr(inner, "default_parameters", None) or {})

    async def generate_response(
        self,
        prompt: str,
        params: Optional[Dict[str, Any]] = None,
        enable_thinking: bool = False,
        use_json: bool = False,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        user_id = get_trace_context().get("user_id")
        if self._can_use_client(user_id):
            config = getattr(self.inner, "config", {}) or {}
            provider = _provider_info_from_config(config)
            try:
                return await _client_request_with_retry(
                    self.executor,
                    user_id,
                    module=getattr(self, "_module_name", "unknown"),
                    prompt=prompt,
                    params=params,
                    enable_thinking=enable_thinking,
                    use_json=use_json,
                    provider=provider,
                )
            except ClientLLMError as exc:
                if _looks_like_json_unsupported(str(exc)):
                    self.logger.warning(
                        "Client model does not support JSON mode, falling back to "
                        "server key for user %s: %s",
                        user_id,
                        exc,
                    )
                    return await self.inner.generate_response(
                        prompt,
                        params=params,
                        enable_thinking=enable_thinking,
                        use_json=use_json,
                        **kwargs,
                    )
                message = (
                    KEY_ERROR_MESSAGE
                    if _looks_like_key_error(str(exc))
                    else CLIENT_ERROR_MESSAGE
                )
                await self.executor.notify_user(user_id, message)
                self.logger.warning(
                    "Client LLM execution failed for user %s: %s", user_id, exc
                )
                raise
            except Exception as exc:
                await self.executor.notify_user(user_id, CLIENT_ERROR_MESSAGE)
                self.logger.warning(
                    "Client LLM execution failed for user %s: %s",
                    user_id,
                    exc,
                )
                raise
        return await self.inner.generate_response(
            prompt,
            params=params,
            enable_thinking=enable_thinking,
            use_json=use_json,
            **kwargs,
        )

    def set_parameters(self, **params: Any) -> None:
        return self.inner.set_parameters(**params)

    def get_interface_info(self) -> Dict[str, Any]:
        return self.inner.get_interface_info()

    def _can_use_client(self, user_id: Optional[str]) -> bool:
        return bool(
            self.executor is not None
            and user_id
            and self.executor.is_enabled(user_id)
        )


class ClientDelegatingVLMInterface(VLMAPIInterface):
    """VLM 接口包装：优先由用户客户端执行，失败回退服务端直连。"""

    def __init__(self, inner: VLMAPIInterface, executor: Optional[ClientLLMExecutor]):
        self.inner = inner
        self.executor = executor
        self.logger = get_logger(__name__)

    async def generate_response(
        self,
        prompt: str,
        image_base64: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        user_id = get_trace_context().get("user_id")
        if self._can_use_client(user_id):
            config = getattr(self.inner, "config", {}) or {}
            provider = _provider_info_from_config(config)
            extra_body = dict(kwargs.get("extra_body") or {})
            enable_thinking = bool(extra_body.get("enable_thinking", False))
            use_json = bool(kwargs.get("response_format"))
            params = {
                key: value
                for key, value in kwargs.items()
                if key not in ("extra_body", "response_format")
            }
            try:
                return await _client_request_with_retry(
                    self.executor,
                    user_id,
                    module=getattr(self, "_module_name", "unknown"),
                    prompt=prompt,
                    params=params,
                    enable_thinking=enable_thinking,
                    use_json=use_json,
                    vlm=True,
                    image_base64=image_base64,
                    provider=provider,
                )
            except ClientLLMError as exc:
                if _looks_like_json_unsupported(str(exc)):
                    self.logger.warning(
                        "Client VLM model does not support JSON mode, falling back "
                        "to server key for user %s: %s",
                        user_id,
                        exc,
                    )
                    return await self.inner.generate_response(
                        prompt,
                        image_base64=image_base64,
                        **kwargs,
                    )
                message = (
                    KEY_ERROR_MESSAGE
                    if _looks_like_key_error(str(exc))
                    else CLIENT_ERROR_MESSAGE
                )
                await self.executor.notify_user(user_id, message)
                self.logger.warning(
                    "Client VLM execution failed for user %s: %s", user_id, exc
                )
                raise
            except Exception as exc:
                await self.executor.notify_user(user_id, CLIENT_ERROR_MESSAGE)
                self.logger.warning(
                    "Client VLM execution failed for user %s: %s",
                    user_id,
                    exc,
                )
                raise
        return await self.inner.generate_response(prompt, image_base64=image_base64, **kwargs)

    def set_parameters(self, **params: Any) -> None:
        return self.inner.set_parameters(**params)

    def get_interface_info(self) -> Dict[str, Any]:
        return self.inner.get_interface_info()

    def _can_use_client(self, user_id: Optional[str]) -> bool:
        return bool(
            self.executor is not None
            and user_id
            and self.executor.is_enabled(user_id, vlm=True)
        )
