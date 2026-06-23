"""
User Profile Updater
--------------------
负责根据单个话题相关对话，判断并更新用户画像（user.description）。
"""

from typing import Dict, Any
import re

from src.utils.logger import get_logger
from src.utils.llm.llm_module import LLMModule
from src.utils.llm.llm_api_interface import LLMAPIFactory


logger = get_logger("UserProfileUpdater")


class UserProfileUpdater:
    def __init__(self, config: Dict[str, Any], prompt_manager):
        self.config = config or {}
        llm_module_cfg = self.config.get("llm_module")
        if not llm_module_cfg:
            raise ValueError("memory_manager.user_profile.llm_module is required")

        llm_cfg = llm_module_cfg.get("llm", {})
        prompt_name = llm_module_cfg.get("prompt_name")
        if not prompt_name:
            raise ValueError("llm_module 配置中缺少 prompt_name")
        prompt_template = prompt_manager.get_template(prompt_name)
        if not prompt_template:
            raise ValueError(f"Prompt 模板未找到: {prompt_name}")
        llm_interface = LLMAPIFactory.create_interface(llm_cfg)

        self.llm = LLMModule(
            module_name="user_profile_updater",
            module_config=llm_module_cfg,
            prompt_template=prompt_template,
            interface=llm_interface,
        )

    async def update_profile(
        self,
        history: Dict[str, Any],
        current_profile: str,
    ) -> str:
        """
        返回值：
        - 空字符串：不需要修改。
        - 非空字符串：新的完整用户画像描述。
        """
        try:
            history_str = "更早对话总结" + history.get("summary", "") + "\n最近对话：\n" + "\n".join(history.get("recent_conversation", []))
            response = await self.llm.generate_response(
                history=history_str or "无",
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
            logger.debug(f"User profile update response indicates no update needed: '{response}'")
            return ""

        # 去掉可能的 markdown 包装
        if text.startswith("```"):
            text = text.strip("`")
            text = re.sub(r"^(text|markdown)\s*", "", text, flags=re.IGNORECASE).strip()

        # 归一化空白
        return "\n".join([line.rstrip() for line in text.splitlines()]).strip()
