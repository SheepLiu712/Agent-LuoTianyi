"""
动态回复器 — 负责任成动态评论的 LLM 回复。

从 DynamicInteractionTask 中拆出的 LLM 调用逻辑，
包括回复生成、JSON 解析、偏好上下文构建等。
"""
from __future__ import annotations

import json
from typing import Any, Optional, TYPE_CHECKING

from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.utils.llm.llm_module import LLMModule
    from src.utils.llm_service import LLMService

logger = get_logger(__name__)


class DynamicReplier:
    """为动态和动态评论生成角色回复。

    封装 LLM 模块注册、回复生成与 JSON 解析逻辑。
    由 DynamicCapability 持有，通过 capability.dynamics.replier 访问。
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.logger = get_logger(__name__)
        self._reply_llm: Optional["LLMModule"] = None
        self._character_name: str = "洛天依"

    def create_llm_module(self, llm_service: "LLMService") -> None:
        """从 config 注册 dynamic reply LLM 模块。"""
        llm_cfg = self.config.get("llm_module")
        if not llm_cfg:
            # 如果没有配置，尝试使用第一个可用的 LLM 接口
            llm_interfaces = getattr(llm_service, "llm_interfaces", None) or {}
            interface_names = list(llm_interfaces.keys())
            if not interface_names:
                return
            llm_cfg = {
                    "llm": {
                    "name": interface_names[0],
                    "enable_thinking": False,
                    "use_json": True,
                },
                "prompt_name": "dynamic_reply_prompt",
            }
        try:
            self._reply_llm = llm_service.register_llm_module("dynamic_reply", llm_cfg)
        except Exception as exc:
            self.logger.warning(f"Dynamic reply module unavailable: {exc}")

    def ensure_llm(self) -> bool:
        """检查 LLM 模块是否可用。"""
        return self._reply_llm is not None

    # ── 角色上下文 ─────────────────────────────────────────

    def set_character_context(self, *, character_name: str) -> None:
        """设置默认角色名称（兼容旧调用；多角色调用应显式传入 character_name）。"""
        self._character_name = character_name

    # ── 回复生成 ───────────────────────────────────────────

    async def generate_reply_for_post(self, item: dict[str, Any], *, character_name: str | None = None) -> str:
        """为动态帖子生成回复文本。

        Args:
            item: 动态条目字典，包含 username, user_description, preferences, content 等字段

        Returns:
            回复文本；LLM 不可用时返回兜底文案
        """
        character_name = character_name or self._character_name
        message_list, target_message = self._build_message_context(
            dynamic=item,
            comments=item.get("thread_comments") or [],
            target=item,
            character_name=character_name,
            target_is_dynamic=True,
        )
        decision = await self._ask_reply_llm(
            item_type="dynamic_post",
            must_reply=True,
            character_name=character_name,
            user_name=item.get("username") or "用户",
            user_description=item.get("user_description") or "",
            preference_context=self._build_preference_context(item.get("preferences") or {}),
            message_list=message_list,
            target_message=target_message,
        )
        reply = str(decision.get("reply") or "").strip()
        if reply:
            return reply
        return "我认真看完啦。谢谢你愿意和我分享这些，之后如果你还想继续说，我会认真听着。"

    async def generate_reply_for_comment(self, item: dict[str, Any], *, character_name: str | None = None) -> dict[str, Any]:
        """为动态评论生成是否回复的判断及回复文本。

        Args:
            item: 动态评论条目字典，包含 username, user_description, preferences, content, dynamic 等字段

        Returns:
            {"should_reply": bool, "reply": str}
        """
        dynamic = item.get("dynamic") or {}
        character_name = character_name or self._character_name
        message_list, target_message = self._build_message_context(
            dynamic=dynamic,
            comments=item.get("thread_comments") or [],
            target=item,
            character_name=character_name,
        )
        decision = await self._ask_reply_llm(
            item_type="dynamic_comment",
            must_reply=False,
            character_name=character_name,
            user_name=item.get("username") or "用户",
            user_description=item.get("user_description") or "",
            preference_context=self._build_preference_context(item.get("preferences") or {}),
            message_list=message_list,
            target_message=target_message,
        )
        reply = str(decision.get("reply") or "").strip()
        should_reply = bool(decision.get("should_reply"))
        if should_reply and not reply:
            reply = "我看到你的补充啦，这件事我会记在心里。"
        return {"should_reply": should_reply and bool(reply), "reply": reply}

    # ── 内部方法 ───────────────────────────────────────────

    async def _ask_reply_llm(
        self,
        *,
        item_type: str,
        must_reply: bool,
        character_name: str,
        user_name: str,
        user_description: str,
        preference_context: str,
        message_list: str,
        target_message: str,
    ) -> dict[str, Any]:
        if self._reply_llm is None:
            return {"should_reply": must_reply, "reply": "" if not must_reply else "谢谢你的分享~"}
        response = await self._reply_llm.generate_response(
            character_name=character_name,
            user_name=user_name,
            user_description=user_description,
            preference_context=preference_context,
            item_type=item_type,
            must_reply="true" if must_reply else "false",
            message_list=message_list,
            target_message=target_message,
        )
        return self._parse_reply_json(response, must_reply=must_reply)

    @staticmethod
    def _parse_reply_json(response: str, *, must_reply: bool) -> dict[str, Any]:
        """解析 LLM 返回的 JSON 响应。

        Args:
            response: LLM 原始返回文本
            must_reply: 是否必须有回复（用于修正 LLM 输出）

        Returns:
            {"should_reply": bool, "reply": str}
        """
        raw = (response or "").strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            raw = "\n".join(lines).strip()
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("dynamic reply payload must be a JSON object")
        should_reply = bool(data.get("should_reply"))
        reply = str(data.get("reply") or "").strip()
        if must_reply:
            should_reply = True
        return {"should_reply": should_reply, "reply": reply}

    @staticmethod
    def _build_preference_context(preferences: dict[str, Any]) -> str:
        """将用户偏好字典构建为提示词上下文字符串。

        Args:
            preferences: 用户偏好字典

        Returns:
            格式化的偏好上文字符串，无偏好时返回空字符串
        """
        if not isinstance(preferences, dict) or not preferences:
            return ""
        parts = []
        if preferences.get("relationship"):
            parts.append(f"用户希望你是他的：{preferences['relationship']}")
        if preferences.get("speaking_style"):
            parts.append(f"用户希望你的表达风格偏向：{preferences['speaking_style']}")
        if preferences.get("personality_traits"):
            traits = preferences["personality_traits"]
            if isinstance(traits, list):
                parts.append(f"用户希望你的性格特点：{'、'.join(str(t) for t in traits if str(t).strip())}")
        if preferences.get("custom_context"):
            parts.append(f"用户补充的上下文：{str(preferences['custom_context']).replace('我', '用户')}")
        return "；".join(parts)

    @classmethod
    def _build_message_context(
        cls,
        *,
        dynamic: dict[str, Any],
        comments: list[dict[str, Any]],
        target: dict[str, Any],
        character_name: str,
        target_is_dynamic: bool = False,
    ) -> tuple[str, str]:
        """将原动态和评论统一整理为消息列表，并标出本次回复目标。"""
        messages: list[dict[str, Any]] = [dynamic]
        if isinstance(comments, list):
            messages.extend(comment for comment in comments if isinstance(comment, dict))

        formatted_messages = [
            cls._format_message(message, index, character_name)
            for index, message in enumerate(messages, start=1)
        ]
        message_list = "\n\n".join(formatted_messages) or "无"

        target_index: int | None = 1 if target_is_dynamic else None
        if target_index is None:
            target_id = str(target.get("id") or "").strip()
            for index, message in enumerate(messages, start=1):
                if target_id and str(message.get("id") or "").strip() == target_id:
                    target_index = index
                    break
                if message is target:
                    target_index = index
                    break

        if target_index is not None:
            target_message = cls._format_message(messages[target_index - 1], target_index, character_name)
        else:
            target_message = "目标消息：\n" + cls._format_message(target, "目标", character_name)
        return message_list, target_message

    @staticmethod
    def _format_message(message: dict[str, Any], index: int | str, character_name: str) -> str:
        author_type = str(message.get("author_type") or "user").strip()
        author_role = {
            "agent": "角色",
            "user": "用户",
            "system": "系统",
        }.get(author_type, author_type or "未知")
        author_name = str(message.get("author_name") or message.get("username") or "").strip()
        if not author_name:
            author_name = character_name if author_type == "agent" else author_role
        content = str(message.get("content") or "").strip()
        return (
            f"消息 {index}：\n"
            f"发布者类型：{author_role}\n"
            f"发布者：{author_name}\n"
            f"内容：{content}"
        )
