from __future__ import annotations

from typing import Any, Optional, TYPE_CHECKING

from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.system.database import DatabaseManager


class DynamicCapability:
    """Publishing capability for agent/world generated dynamics and comments."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.logger = get_logger(__name__)
        self.database_manager: "DatabaseManager | None" = None

    def wire_dependencies(self, *, database_manager: "DatabaseManager") -> None:
        self.database_manager = database_manager
        self.ensure_dependencies()

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

    def publish_system_dynamic(
        self,
        *,
        content: str,
        source_type: str = "system_notice",
        source_id: str | None = None,
        visibility: str = "global",
        allow_comment: bool = False,
    ) -> tuple[bool, str, Optional[dict[str, Any]]]:
        self.ensure_dependencies()
        return self.database_manager.dynamic_store.create_dynamic(
            author_type="system",
            author_id="system",
            owner_user_id=None,
            visibility=visibility,
            content=content,
            source_type=source_type,
            source_id=source_id,
            allow_comment=allow_comment,
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
