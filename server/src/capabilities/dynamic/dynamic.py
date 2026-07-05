from __future__ import annotations

from typing import Any, Optional, TYPE_CHECKING

from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.system.database import DatabaseManager
    from src.utils.llm_service import LLMService
    from src.utils.llm.llm_module import LLMModule
    from src.utils.llm.llm_api_interface import LLMContentInspectionError

from src.capabilities.dynamic.dynamic_replier import DynamicReplier


class DynamicCapability:
    """Publishing capability for agent/world generated dynamics and comments.

    Also responsible for generating world dynamic content via LLM (moved from LuoTianyiAgent),
    and dynamic reply generation via DynamicReplier.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.logger = get_logger(__name__)
        self.database_manager: "DatabaseManager | None" = None
        self._dynamic_composer: "LLMModule | None" = None
        # Character config — populated via wire_character_context
        self._character_name: str = "洛天依"
        self._character_persona: str = ""
        self._speaking_style: str = ""
        # 动态回复器
        self.replier: DynamicReplier = DynamicReplier(self.config.get("reply", {}))

    def create_dynamic_composer_module(self, llm_service: "LLMService") -> None:
        """从 config 注册 world dynamic composer LLM 模块。"""
        composer_cfg = self.config.get("dynamic_composer")
        if composer_cfg:
            self._dynamic_composer = llm_service.register_llm_module("dynamic_composer", composer_cfg)
        # 同时注册动态回复 LLM 模块
        self.replier.create_reply_llm_module(llm_service)

    def wire_dependencies(self, *, database_manager: "DatabaseManager") -> None:
        self.database_manager = database_manager
        self.ensure_dependencies()

    def wire_character_context(
        self,
        *,
        character_name: str = "洛天依",
        character_persona: str = "",
        speaking_style: str = "",
    ) -> None:
        """设置角色上下文（供动态文案生成和回复使用）。"""
        self._character_name = character_name
        self._character_persona = character_persona
        self._speaking_style = speaking_style
        self.replier.set_character_context(character_name=character_name)

    def ensure_dependencies(self) -> None:
        if self.database_manager is None:
            raise RuntimeError("DynamicCapability dependencies are missing: database_manager")

    def publish_agent_dynamic(
        self,
        *,
        character_id: str,
        content: str,
        source_type: str,
        source_id: str | None = None,
        visibility: str = "global",
        owner_user_id: str | None = None,
        allow_comment: bool = True,
        image_refs: list[Any] | None = None,
    ) -> tuple[bool, str, Optional[dict[str, Any]]]:
        self.ensure_dependencies()
        return self.database_manager.dynamic_store.create_dynamic(
            author_type="agent",
            author_id=character_id,
            owner_user_id=owner_user_id,
            visibility=visibility,
            content=content,
            source_type=source_type,
            source_id=source_id,
            allow_comment=allow_comment,
            image_refs=image_refs,
            memory_policy="disabled",
            memory_status="disabled",
            reply_status="not_applicable",
        )

    def publish_agent_comment(
        self,
        *,
        dynamic_id: str,
        owner_user_id: str,
        content: str,
        character_id: str = "luotianyi",
        parent_comment_id: str | None = None,
    ) -> tuple[bool, str, Optional[dict[str, Any]]]:
        self.ensure_dependencies()
        return self.database_manager.dynamic_store.create_dynamic_comment(
            dynamic_id=dynamic_id,
            author_type="agent",
            author_id=character_id,
            owner_user_id=owner_user_id,
            content=content,
            parent_comment_id=parent_comment_id,
            memory_policy="disabled",
            memory_status="disabled",
            reply_status="not_applicable",
        )

    async def generate_world_dynamic_content(
        self,
        *,
        dynamic_type: str,
        instruction: str,
        structured_context: str,
    ) -> str:
        """为 world 事件生成角色动态文案（从 LuoTianyiAgent 移入）。

        Args:
            dynamic_type: 动态类型，如 "citywalk" / "song_learned"
            instruction: 针对该动态类型的特定生成要求
            structured_context: 结构化的上下文信息

        Returns:
            生成的动态文案；如果 LLM 不可用或生成失败，返回空字符串。
        """
        if self._dynamic_composer is None:
            return ""
        try:
            response = await self._dynamic_composer.generate_response(
                character_name=self._character_name,
                character_persona=self._character_persona,
                speaking_style=self._speaking_style,
                dynamic_type=dynamic_type,
                instruction=instruction,
                structured_context=structured_context,
            )
            text = str(response or "").strip()
            return text
        except Exception as exc:
            self.logger.warning(f"Dynamic composer failed: {exc}")
            return ""
