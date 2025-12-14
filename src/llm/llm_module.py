from .llm_api_interface import LLMAPIInterface, LLMAPIFactory
from .prompt_manager import PromptTemplate, PromptManager

class LLMModule:
    def __init__(self, module_config:dict, prompt_manager: PromptManager) -> None:
        llm_config = module_config.get("llm", {})
        prompt_name = module_config.get("prompt_name", None)
        if not prompt_name:
            raise ValueError("prompt_name must be specified in module_config")
        self.llm_client: LLMAPIInterface = LLMAPIFactory.create_interface(llm_config)
        self.prompt_template: PromptTemplate = prompt_manager.get_template(prompt_name)

    def generate_response(self, **kwargs) -> str:
        prompt = self.prompt_template.render(**kwargs)
        response = self.llm_client.generate_response(prompt)
        return response