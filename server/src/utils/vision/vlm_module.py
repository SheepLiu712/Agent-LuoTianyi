from src.utils.vision.vlm_api_interface import VLMAPIInterface
from src.utils.llm.prompt_manager import PromptTemplate
from src.utils.logger import get_logger


class VLMModule:
    def __init__(
        self,
        module_name: str,
        module_config: dict,
        prompt_template: PromptTemplate,
        interface: VLMAPIInterface,
    ) -> None:
        self.name = module_name
        self.logger = get_logger(f"VLMModule:{module_name}")

        self.config = module_config
        self.enable_thinking = module_config.get("enable_thinking", False)
        self.use_json = module_config.get("use_json", False)
        self.vlm_client: VLMAPIInterface = interface
        self.prompt_template: PromptTemplate = prompt_template

        self.params = module_config.get("params", {})

    async def generate_response(self, image_base64: str, **kwargs) -> dict:
        """生成 VLM 响应，返回完整字典（含 content / usage / response_time_s）

        :param image_base64: 图片的 Base64 数据 URI 或可访问的图片 URL
        :param kwargs: 渲染 prompt 模板的变量
        :return: {"content": str, "usage": dict, "response_time_s": float}
        """
        prompt = self.prompt_template.render(**kwargs)
        response = await self.vlm_client.generate_response(prompt, image_base64=image_base64)
        token_usage = response.get("usage", {})
        self.logger.debug(
            f"Token usage - Prompt: {token_usage.get('prompt_tokens', 0)}, "
            f"Completion: {token_usage.get('completion_tokens', 0)}, "
            f"Total: {token_usage.get('total_tokens', 0)}"
            f" | Response time: {response.get('response_time_s', 'N/A')}s"
        )
        return response