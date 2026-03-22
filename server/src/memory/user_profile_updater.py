"""
User Profile Updater
--------------------
负责根据单个话题相关对话，判断并更新用户画像（user.description）。
"""

from typing import Dict, Any
import re

from ..utils.logger import get_logger
from ..utils.llm.llm_module import LLMModule


logger = get_logger("UserProfileUpdater")


class UserProfileUpdater:
    def __init__(self, config: Dict[str, Any], prompt_manager):
        self.config = config or {}
        llm_cfg = self.config.get("llm_module")
        if not llm_cfg:
            raise ValueError("memory_manager.user_profile.llm_module is required")
        self.llm = LLMModule(llm_cfg, prompt_manager)

    async def update_profile(
        self,
        history: str,
        current_dialogue: str,
        current_profile: str,
    ) -> str:
        """
        返回值：
        - 空字符串：不需要修改。
        - 非空字符串：新的完整用户画像描述。
        """
        try:
            response = await self.llm.generate_response(
                history=history or "",
                current_dialogue=current_dialogue or "",
                current_profile=current_profile or "",
            )
        except Exception as e:
            logger.warning(f"User profile update LLM call failed: {e}")
            return ""

        normalized = self._normalize_response(response)
        if not normalized:
            return ""

        if normalized == (current_profile or "").strip():
            return ""

        return normalized

    def _normalize_response(self, response: str) -> str:
        text = (response or "").strip()
        if not text:
            return ""

        lowered = text.lower()
        no_update_tokens = {
            "no_update",
            "none",
            "null",
            "无需更新",
            "不需要更新",
            "无需修改",
            "不需要修改",
            "无",
            "空",
            "保持不变",
        }
        if lowered in no_update_tokens:
            return ""

        # 去掉可能的 markdown 包装
        if text.startswith("```"):
            text = text.strip("`")
            text = re.sub(r"^(text|markdown)\s*", "", text, flags=re.IGNORECASE).strip()

        # 归一化空白
        return "\n".join([line.rstrip() for line in text.splitlines()]).strip()
