from src.utils.llm.llm_api_interface import LLMAPIInterface
from src.utils.llm.prompt_manager import PromptTemplate
from src.utils.logger import get_logger

class LLMModule:
    def __init__(self, module_name: str, module_config:dict, prompt_template: PromptTemplate, interface: LLMAPIInterface) -> None:
        self.name = module_name
        self.logger = get_logger(f"LLMModule:{module_name}")

        self.config = module_config
        self.enable_thinking = module_config.get("enable_thinking", False)
        self.use_json = module_config.get("use_json", False)
        self.llm_client : LLMAPIInterface = interface
        self.prompt_template : PromptTemplate = prompt_template

        self.params = self.llm_client.default_parameters.copy().update(module_config.get("params", {}))

    async def generate_response(self, **kwargs) -> str:
        prompt = self.prompt_template.render(**kwargs)
        response = await self.llm_client.generate_response(
            prompt,
            params=self.params,
            enable_thinking=self.enable_thinking,
            use_json=self.use_json
        )
        token_usage = response.get("usage", {})
        self.logger.debug(
            f"Token usage - Prompt: {token_usage.get('prompt_tokens', 0)}, "
            f"Completion: {token_usage.get('completion_tokens', 0)}, Total: {token_usage.get('total_tokens', 0)}"
            f" | Response time: {response.get('response_time_s', 'N/A')}s"
        )
        return response["content"]