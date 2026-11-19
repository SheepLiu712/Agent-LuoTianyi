"""聊天记录的稳定时间线；导入身份变化不改变同一时刻内的先后。"""

from collections.abc import Mapping
from typing import Any

TRANSFER_ORDER_KEY = "_transfer_order"


def conversation_order(
    identity: str, user_id: str, metadata: Mapping[str, Any] | None = None
) -> tuple[str, str, str, str]:
    """普通记录沿用 UUID 顺序，混合来源同键时以稳定来源身份打破并列。"""
    metadata = metadata or {}
    order = metadata.get(TRANSFER_ORDER_KEY, {"id": identity, "user_id": user_id})
    origin = metadata.get("_transfer_origin", {"id": identity, "user_id": user_id})
    for value in (order, origin):
        if not isinstance(value, dict) or set(value) != {"id", "user_id"}:
            raise ValueError("INVALID_CONVERSATION_ORDER")
        if any(not isinstance(value[key], str) or not value[key] for key in ("id", "user_id")):
            raise ValueError("INVALID_CONVERSATION_ORDER")
    return order["id"], order["user_id"], origin["user_id"], origin["id"]
