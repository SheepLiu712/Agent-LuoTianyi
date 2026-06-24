from src.utils.logger import get_logger
from typing import TYPE_CHECKING, Optional, Dict

if TYPE_CHECKING:
    from src.utils.vision.vlm_module import VLMModule
    from src.utils.llm_service import LLMService

class ImageUnderstanding:
    def __init__(self, config: Dict, vlm_module: Optional["VLMModule"] = None):
        self.config = config
        self.logger = get_logger("ImageUnderstanding")
        self.vlm_module = vlm_module

    def create_vlm_module(self, llm_service: "LLMService") -> None:
        """
        创建视觉语言模型模块（VLMModule）。

        :param llm_service: LLMService 实例，用于提供语言模型服务
        """
        self.vlm_module = llm_service.register_vlm_module(self.config.get("vlm_module", {}))

    def describe_image(self, image_base64: str, **kwargs) -> str:
        """
        使用视觉语言模型描述图像内容。

        :param image_base64: 输入图像的Base64编码
        :param kwargs: 其他可选参数
        :return: 图像描述文本
        """
        if not self.vlm_module:
            raise RuntimeError("VLMModule is not initialized. Call create_vlm_module first.")
        
        response = self.vlm_module.generate_response(image_base64=image_base64, **kwargs)
        description = response["content"]
        description = f"[一张图片]:{description}"
        return description