from src.utils.vision.vlm_api_interface import VLMAPIInterface
from src.utils.llm.prompt_manager import PromptTemplate
from src.utils.llm.client_llm_executor import ClientLLMExecutionError, notify_fallback
from src.utils.logger import get_logger
from src.system.observability import get_trace_context
from typing import Any, Dict


class VLMModule:
    def __init__(
        self,
        module_name: str,
        module_config: dict,
        prompt_template: PromptTemplate,
        interface: VLMAPIInterface,
        client_llm_executor: Any = None,
    ) -> None:
        self.name = module_name
        self.logger = get_logger(f"VLMModule:{module_name}")

        self.config = module_config
        vlm_config = module_config.get("vlm", {})
        self.enable_thinking = module_config.get("enable_thinking", vlm_config.get("enable_thinking", False))
        self.use_json = module_config.get("use_json", vlm_config.get("use_json", False))
        self.vlm_client: VLMAPIInterface = interface
        self.prompt_template: PromptTemplate = prompt_template
        self.client_llm_executor = client_llm_executor
        self.client_model_type = str(vlm_config.get("client_model_type") or "").strip()

        self.params = module_config.get("params", vlm_config.get("params", {}))

    async def generate_response(self, image_base64: str, **kwargs) -> dict:
        """生成 VLM 响应，返回完整字典（含 content / usage / response_time_s）

        :param image_base64: 图片的 Base64 数据 URI 或可访问的图片 URL
        :param kwargs: 渲染 prompt 模板的变量
        :return: {"content": str, "usage": dict, "response_time_s": float}
        """
        prompt = self.prompt_template.render(**kwargs)
        request_kwargs = dict(self.params or {})
        if self.enable_thinking:
            extra_body = dict(request_kwargs.get("extra_body") or {})
            extra_body["enable_thinking"] = True
            request_kwargs["extra_body"] = extra_body
        if self.use_json:
            request_kwargs["response_format"] = {"type": "json_object"}
        response = await self._generate(
            prompt,
            image_base64=image_base64,
            request_kwargs=request_kwargs,
        )
        token_usage = response.get("usage", {})
        self.logger.debug(
            f"Token usage - Prompt: {token_usage.get('prompt_tokens', 0)}, "
            f"Completion: {token_usage.get('completion_tokens', 0)}, "
            f"Total: {token_usage.get('total_tokens', 0)}"
            f" | Response time: {response.get('response_time_s', 'N/A')}s"
        )
        return response

    async def _generate(
        self,
        prompt: str,
        *,
        image_base64: str,
        request_kwargs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """优先按客户端模型类型委托；未配置/未启用时用服务端接口直连。"""
        if self.client_model_type and self.client_llm_executor is not None:
            user_id = get_trace_context().get("user_id")
            try:
                response = await self.client_llm_executor.delegate(
                    user_id,
                    module=self.name,
                    model_type=self.client_model_type,
                    model_kind="vlm",
                    prompt=prompt,
                    params=self.params,
                    enable_thinking=self.enable_thinking,
                    use_json=self.use_json,
                    image_base64=image_base64,
                )
            except ClientLLMExecutionError as exc:
                self.logger.warning(
                    "Client delegation failed for module %s: %s; falling back to server interface",
                    self.name,
                    exc,
                )
                await notify_fallback(
                    self.client_llm_executor, user_id, self.name, exc
                )
                response = None
            if response is not None:
                return response
        return await self.vlm_client.generate_response(
            prompt,
            image_base64=image_base64,
            **request_kwargs,
        )
