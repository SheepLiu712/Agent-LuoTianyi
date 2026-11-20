from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.infrastructure.models.llm.module import LLMModule
    from src.infrastructure.models.service import LLMService
    from src.infrastructure.persistence.database import DatabaseManager

from src.agent.skills.expression._dynamic_replier import DynamicReplier


class DynamicOperations:
    """Publishing capability for agent/world generated dynamics and comments.

    Also responsible for generating world dynamic content via LLM,
    and dynamic reply generation via DynamicReplier.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.logger = get_logger(__name__)
        self.database_manager: "DatabaseManager | None" = None
        self._dynamic_composer: "LLMModule | None" = None
        # 动态回复器
        self.replier: DynamicReplier = DynamicReplier(
            self.config.get("dynamic_replier") or self.config.get("reply", {})
        )

    def create_llm_module(self, llm_service: "LLMService") -> None:
        """从 config 注册 world dynamic composer LLM 模块。"""
        composer_cfg = self._module_config(self.config.get("dynamic_composer"))
        if composer_cfg:
            self._dynamic_composer = llm_service.register_llm_module("skill.dynamic.generate", composer_cfg)
        # 同时注册动态回复 LLM 模块
        self.replier.create_llm_module(llm_service)

    @staticmethod
    def _module_config(config: Any) -> dict[str, Any]:
        if not isinstance(config, dict):
            return {}
        llm_module = config.get("llm_module")
        if isinstance(llm_module, dict):
            return llm_module
        return config

    def wire_dependencies(self, *, database_manager: "DatabaseManager") -> None:
        self.database_manager = database_manager
        self.ensure_dependencies()

    def ensure_dependencies(self) -> None:
        if self.database_manager is None:
            raise RuntimeError("DynamicOperations dependencies are missing: database_manager")

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
        idempotent_by_source: bool = False,
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
            idempotent_by_source=idempotent_by_source,
        )

    async def generate_world_dynamic_content(
        self,
        *,
        character_name: str,
        character_persona: str,
        speaking_style: str,
        dynamic_type: str,
        instruction: str,
        structured_context: str,
    ) -> str:
        """为 world 事件生成角色动态文案。

        Args:
            dynamic_type: 动态类型，如 "citywalk" / "song_learned"
            instruction: 针对该动态类型的特定生成要求
            structured_context: 结构化的上下文信息

        Returns:
            生成的非空动态文案；模型不可用或生成失败时抛出错误。
        """
        if self._dynamic_composer is None:
            raise RuntimeError("agent_runtime.skills.dynamic.dynamic_composer 未配置")
        response = await self._dynamic_composer.generate_response(
            character_name=character_name,
            character_persona=character_persona,
            speaking_style=speaking_style,
            dynamic_type=dynamic_type,
            instruction=instruction,
            structured_context=structured_context,
        )
        if not isinstance(response, str) or not response.strip():
            raise ValueError("动态生成模型未返回正文")
        return response.strip()
