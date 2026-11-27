"""SQL 与缓存使用同一条聊天时间线：显式整数序号决定消息先后。"""

import json

from src.domain.conversation_order import conversation_order


def conversation_order_columns(model=None):
    """返回显式序号排序键；旧库回填后不再依赖时间戳或 JSON 排序元数据。"""
    if model is None:
        # 避免 database 包装配服务时再次穿入尚未完成加载的排序模块。
        from src.infrastructure.persistence.database.sql_database import Conversation

        model = Conversation
    return (model.index, model.timestamp, model.uuid)


def conversation_row_key(row, user_id=""):
    """接受现有 SQL row 或缓存字典，主键为 (user, character) 内单调序号。"""
    if isinstance(row, dict):
        timestamp, identity, metadata = row["timestamp"], row["uuid"], row.get("meta_data")
        owner = row.get("user_id", user_id)
        index = row.get("index")
    else:
        timestamp, identity, metadata, owner = row.timestamp, row.uuid, row.meta_data, row.user_id
        index = getattr(row, "index", None)
    if index is not None:
        return index, timestamp, identity
    # 防御性回退：只用于尚未回填的旧缓存或测试行，生产读取路径不再产生 NULL 序号。
    if isinstance(metadata, str):
        metadata = json.loads(metadata) if metadata else {}
    return timestamp, *conversation_order(identity, owner, metadata)
