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
        if self.vlm_module is not None:
            return
        self.vlm_module = llm_service.register_vlm_module(
            "image_understanding",
            self.config.get("vlm_module", {}),
        )

    def ensure_dependencies(self) -> None:
        """检查图像理解能力依赖已经初始化。"""
        if self.vlm_module is None:
            raise RuntimeError("ImageUnderstanding dependency is missing: vlm_module")

    async def describe_image(self, image_base64: str, **kwargs) -> str:
        """
        使用视觉语言模型描述图像内容。

        :param image_base64: 输入图像的Base64编码
        :param kwargs: 其他可选参数
        :return: 图像描述文本
        """
        if not self.vlm_module:
            raise RuntimeError("VLMModule is not initialized. Call create_vlm_module first.")
        
        response = await self.vlm_module.generate_response(image_base64=image_base64, **kwargs)
        description = response["content"]
        description = f"[一张图片]:{description}"
        return description
