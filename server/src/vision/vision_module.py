from typing import Dict, Any
from ..llm.prompt_manager import PromptManager
from ..utils.logger import get_logger
from .vlm_module import VLMModule

class VisionModule:
    def __init__(self, config: Dict, prompt_manager: PromptManager) -> None:
        self.logger = get_logger(__name__)
        self.config = config
        self.prompt_manager = prompt_manager
        # 初始化视觉模型相关组件
        self.vlm_module = VLMModule(config["vlm_module"], prompt_manager)

    async def describe_image(self, image_base64: str, **kwargs) -> str:
        """
        使用视觉模型描述图像内容

        :param image_base64: 输入图像的Base64编码
        :param kwargs: 其他可选参数
        :return: 图像描述文本
        """
        response = await self.vlm_module.generate_response(image_base64=image_base64, **kwargs)
        self.logger.info(f"Generated image description: {response}")
        return response