from .vlm_api_interface import VLMAPIInterface, VLMAPIFactory
from ..llm.prompt_manager import PromptTemplate, PromptManager

class VLMModule:
    def __init__(self, module_config:dict, prompt_manager: PromptManager) -> None:
        vlm_config = module_config.get("vlm", {})
        prompt_name = module_config.get("prompt_name", None)
        if not prompt_name:
            raise ValueError("prompt_name must be specified in module_config")
        self.vlm_client: VLMAPIInterface = VLMAPIFactory.create_interface(vlm_config)
        self.prompt_template: PromptTemplate = prompt_manager.get_template(prompt_name)

    async def generate_response(self, image_base64: str, **kwargs) -> str:
        prompt = self.prompt_template.render(**kwargs)
        response = await self.vlm_client.generate_response(prompt, image_base64=image_base64)
        return response 