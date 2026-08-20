from src.utils.llm.llm_api_interface import LLMAPIInterface
from src.utils.llm.prompt_manager import PromptTemplate
from src.utils.llm.client_llm_executor import ClientLLMExecutionError, notify_fallback
from src.utils.logger import get_logger
from src.system.observability import get_observability_service, get_trace_context
from typing import Dict, List, Any
import time

class LLMModule:
    def __init__(
        self,
        module_name: str,
        llm_config: dict,
        prompt_template: PromptTemplate,
        interface: LLMAPIInterface,
        client_llm_executor: Any = None,
    ) -> None:
        self.name = module_name
        self.logger = get_logger(f"LLMModule:{module_name}")

        self.config = llm_config
        self.enable_thinking = llm_config.get("enable_thinking", False)
        self.use_json = llm_config.get("use_json", False)
        self.llm_client : LLMAPIInterface = interface
        self.prompt_template : PromptTemplate = prompt_template
        self.client_llm_executor = client_llm_executor
        self.client_model_type = str(llm_config.get("client_model_type") or "").strip()

        self.params = self.llm_client.default_parameters.copy()
        self.params.update(llm_config.get("params", {}))

        self._recent_response = None  # 存储最近一次的响应结果

    async def generate_response(self, **kwargs) -> str:
        prompt = self.prompt_template.render(**kwargs)
        observability = get_observability_service()
        trace_context = get_trace_context()
        interface_info = self.llm_client.get_interface_info()
        interface_name = self.config.get("name") or interface_info.get("type")
        model_name = interface_info.get("model")
        started = time.perf_counter()
        try:
            response = await self._generate(prompt)
            latency_ms = (time.perf_counter() - started) * 1000.0
            self._recent_response = response  # 存储最近一次的响应结果
            token_usage = response.get("usage", {}) or {}
            self.logger.debug(
                f"Token usage - Prompt: {token_usage.get('prompt_tokens', 0)}, "
                f"Completion: {token_usage.get('completion_tokens', 0)}, Total: {token_usage.get('total_tokens', 0)}"
                f" | Response time: {response.get('response_time_s', 'N/A')}s"
            )
            if observability is not None:
                observability.record_llm_call(
                    module_name=self.name,
                    interface_name=interface_name,
                    model_name=model_name,
                    latency_ms=latency_ms,
                    success=True,
                    prompt_tokens=token_usage.get("prompt_tokens", 0),
                    completion_tokens=token_usage.get("completion_tokens", 0),
                    total_tokens=token_usage.get("total_tokens", 0),
                    trace_id=trace_context.get("trace_id"),
                    user_id=trace_context.get("user_id"),
                    metadata={
                        "enable_thinking": self.enable_thinking,
                        "use_json": self.use_json,
                    },
                )
            return response["content"]
        except Exception as exc:
            if observability is not None:
                observability.record_llm_call(
                    module_name=self.name,
                    interface_name=interface_name,
                    model_name=model_name,
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    success=False,
                    error_type=exc.__class__.__name__,
                    error_message=str(exc),
                    trace_id=trace_context.get("trace_id"),
                    user_id=trace_context.get("user_id"),
                )
            raise

    async def _generate(self, prompt: str) -> Dict[str, Any]:
        """优先按客户端模型类型委托；未配置/未启用时用服务端接口直连。"""
        if self.client_model_type and self.client_llm_executor is not None:
            user_id = get_trace_context().get("user_id")
            try:
                response = await self.client_llm_executor.delegate(
                    user_id,
                    module=self.name,
                    model_type=self.client_model_type,
                    prompt=prompt,
                    params=self.params,
                    enable_thinking=self.enable_thinking,
                    use_json=self.use_json,
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
        return await self.llm_client.generate_response(
            prompt,
            params=self.params,
            enable_thinking=self.enable_thinking,
            use_json=self.use_json,
        )
    
    @property
    def recent_response(self):
        """获取最近一次的响应结果"""
        return self._recent_response
    
    def get_variables(self) -> List[str]:
        """获取模块的变量信息"""
        return self.prompt_template.get_variables()
