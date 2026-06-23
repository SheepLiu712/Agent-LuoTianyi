from typing import Dict, Any
from src.utils.llm.prompt_manager import PromptManager
from src.utils.logger import get_logger
from src.utils.vision.vlm_module import VLMModule
from src.utils.vision.vlm_api_interface import VLMAPIFactory


class VisionModule:
    def __init__(self, config: Dict, prompt_manager: PromptManager) -> None:
        self.logger = get_logger(__name__)
        self.config = config
        self.prompt_manager = prompt_manager

        vlm_module_cfg = config.get("vlm_module", {})
        vlm_cfg = vlm_module_cfg.get("vlm", {})
        prompt_name = vlm_module_cfg.get("prompt_name")

        if not prompt_name:
            raise ValueError("vlm_module 配置中缺少 prompt_name")

        vlm_interface = VLMAPIFactory.create_interface(vlm_cfg)
        prompt_template = prompt_manager.get_template(prompt_name)

        self.vlm_module = VLMModule(
            module_name="vision_module",
            module_config=vlm_module_cfg,
            prompt_template=prompt_template,
            interface=vlm_interface,
        )

    async def describe_image(self, image_base64: str, **kwargs) -> str:
        """
        使用视觉模型描述图像内容

        :param image_base64: 输入图像的Base64编码
        :param kwargs: 其他可选参数
        :return: 图像描述文本
        """
        response = await self.vlm_module.generate_response(image_base64=image_base64, **kwargs)
        self.logger.info(f"Generated image description: {response}")
        return response["content"]