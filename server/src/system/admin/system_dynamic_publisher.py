"""
系统动态发布器 — 供 admin 管理接口使用，发布系统公告类动态。

从 DynamicCapability 拆出，因为系统动态属于运营管理范畴，
而非角色的能力（capability）。
"""
from __future__ import annotations

from typing import Any, Optional, TYPE_CHECKING

from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.system.database import DatabaseManager

logger = get_logger(__name__)


def publish_system_dynamic(
    database_manager: "DatabaseManager",
    *,
    content: str,
    source_type: str = "system_notice",
    source_id: str | None = None,
    visibility: str = "global",
    allow_comment: bool = False,
) -> tuple[bool, str, Optional[dict[str, Any]]]:
    """发布一条系统公告类动态。

    Args:
        database_manager: 数据库管理器实例
        content: 动态正文
        source_type: 来源类型，默认 "system_notice"
        source_id: 来源 ID，可选
        visibility: 可见性，默认 "global"
        allow_comment: 是否允许评论，默认 False

    Returns:
        (ok, message, item_dict | None)
    """
    return database_manager.dynamic_store.create_dynamic(
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
