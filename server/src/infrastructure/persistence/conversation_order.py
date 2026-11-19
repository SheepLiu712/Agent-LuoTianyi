"""SQL 与缓存使用同一条聊天时间线，排序依据与可迁移身份分离。"""

import json

from sqlalchemy import func

from src.domain.conversation_order import TRANSFER_ORDER_KEY, conversation_order


def conversation_order_columns(model=None):
    """返回可用于正序/倒序查询的列，默认记录保持既有 UUID 排序。"""
    if model is None:
        # 避免 database 包装配服务时再次穿入尚未完成加载的排序模块。
        from src.infrastructure.persistence.database.sql_database import Conversation

        model = Conversation
    return (
        model.timestamp,
        func.coalesce(func.json_extract(model.meta_data, f"$.{TRANSFER_ORDER_KEY}.id"), model.uuid),
        func.coalesce(func.json_extract(model.meta_data, f"$.{TRANSFER_ORDER_KEY}.user_id"), model.user_id),
        func.coalesce(func.json_extract(model.meta_data, "$._transfer_origin.user_id"), model.user_id),
        func.coalesce(func.json_extract(model.meta_data, "$._transfer_origin.id"), model.uuid),
    )


def conversation_row_key(row, user_id=""):
    """接受现有 SQL row 或缓存字典，供时间线比较和缓存合并使用。"""
    if isinstance(row, dict):
        timestamp, identity, metadata = row["timestamp"], row["uuid"], row.get("meta_data")
        owner = row.get("user_id", user_id)
    else:
        timestamp, identity, metadata, owner = row.timestamp, row.uuid, row.meta_data, row.user_id
    if isinstance(metadata, str):
        metadata = json.loads(metadata) if metadata else {}
    return timestamp, *conversation_order(identity, owner, metadata)
