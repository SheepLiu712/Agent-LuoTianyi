from .sql_database import init_sql_db, get_sql_db
from sqlalchemy.orm import Session
from .vector_store import VectorStore, init_vector_store, get_vector_store
from .sql_database import User, KnowledgeBuffer, Conversation, Base, MemoryRecord, MemoryUpdateRecord
from .redis_buffer import init_redis_buffer, get_redis_buffer
from .knowledge_graph import KnowledgeGraph, init_knowledge_graph, get_knowledge_graph
from redis import Redis
import os
import base64

import json
from typing import Dict, Any, Optional, List
from datetime import datetime
import uuid
from redis import WatchError

from ..utils.logger import get_logger
from ..types import ConversationItem, KnowledgeItem, MemoryUpdateCommand


logger = get_logger("database")


def init_all_databases(config: Dict[str, Any]) -> None:
    """初始化所有数据库组件"""
    try:
        init_sql_db(config.get("sql_db_folder", "data/database"), config.get("sql_db_file", "luotianyi.db"))
        init_vector_store(config.get("vector_store", {}))
        init_redis_buffer(config.get("redis", {}))
        init_knowledge_graph(config.get("knowledge_graph", {}))
        logger.info("All databases initialized successfully.")
    except Exception as e:
        logger.error(f"Error initializing databases: {e}")
        raise


def prefill_buffer(db: Session, redis: Redis, user_id: str, types: List[str] = ["all"]) -> bool:
    """
    将用户的上下文信息预加载到 Redis 中，提升响应速度。
    需要载入的包括两部分：①上下文，由总结summary和多个最近的对话组成；②上下文对应的知识库内容。

    :param db: 数据库会话
    :type db: Session
    :param redis: Redis
    :type redis: Redis
    :param user_id: 用户 uuid
    :type user_id: str
    :param types: 预加载的内容类型，默认为 "all"，可选 "context" 或 "knowledge"
    :type types: List[str]
    """

    user = db.query(User).filter(User.uuid == user_id).first()
    if not user:
        logger.error(f"User {user_id} not found for prefill_buffer.")
        return False

    try:
        # 1. 加载上下文
        if "all" in types or "context" in types:
            # 从数据库中获取用户的上下文信息
            summary = user.context_summary or ""
            context_memory_count = user.context_memory_count or 0
            context_conversations = (
                db.query(Conversation)
                .filter(Conversation.user_id == user_id)
                .order_by(Conversation.timestamp.desc())
                .limit(context_memory_count)
                .all()
            )

            # 组织上下文信息
            context_info = {
                "summary": summary,
                "conversations": [
                    {
                        "timestamp": conv.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                        "source": conv.source,
                        "content": conv.content,
                        "type": conv.type,
                    }
                    for conv in reversed(context_conversations)  # 保持时间顺序
                ],
            }

            # 将上下文信息写入 Redis
            redis_key = f"user_context:{user_id}"
            redis.setex(redis_key, 3600, json.dumps(context_info, ensure_ascii=False))  # 1小时过期
            logger.info(f"Prefilled context buffer for user {user_id} in Redis.")


        # 2. 加载知识库缓存
        if "all" in types or "knowledge" in types:
            # 从数据库中获取用户的最近知识库缓存
            knowledge_buffers = (
                db.query(KnowledgeBuffer).filter(KnowledgeBuffer.user_id == user_id).order_by(KnowledgeBuffer.uuid.asc()).all()
            )
            knowledge_contents = [kb.content for kb in knowledge_buffers]
            knowledge_key = f"user_knowledge:{user_id}"
            redis.setex(knowledge_key, 3600, json.dumps(knowledge_contents, ensure_ascii=False))  # 1小时过期
            logger.info(f"Prefilled knowledge buffer for user {user_id} in Redis.")

    
        # 3. 加载用户昵称
        if "all" in types or "nickname" in types:
            nickname = user.nickname or ""
            nickname_key = f"user_nickname:{user_id}"
            redis.setex(nickname_key, 3600, nickname)  # 1小时过期
            logger.info(f"Prefilled nickname for user {user_id} in Redis.")

        # 4. 加载最近的记忆更新命令
        if "all" in types or "recent_memory_update" in types:
            recent_update = (
                db.query(MemoryUpdateRecord)
                .filter(MemoryUpdateRecord.user_id == user_id)
                .order_by(MemoryUpdateRecord.created_at.desc())
                .limit(10)
                .all()
            )
            recent_updates_list = []
            for record in reversed(recent_update):
                try:
                    cmd = json.loads(record.update_command)
                    recent_updates_list.append(cmd)
                except json.JSONDecodeError:
                    logger.warning(f"Failed to decode MemoryUpdateCommand for user {user_id}, record {record.update_cmd_uuid}")
                    continue
            recent_update_key = f"user_recent_memory_update:{user_id}"
            redis.setex(recent_update_key, 3600, json.dumps(recent_updates_list, ensure_ascii=False))  # 1小时过期
            logger.info(f"Prefilled recent memory update for user {user_id} in Redis.")

        return True
        

    except Exception as e:
        import traceback as tb

        tb.print_exc()
        logger.error(f"Error in prefill_buffer for user {user_id}: {e}")
        return False


def add_conversations(db: Session, redis: Redis, user_id: str, conversation_data: List[ConversationItem], commit=True) -> List[str]:
    """
    在数据库中增加一条对话记录，同时user的对话总数all_memory_count加一。context_memory_count加一。
    在 Redis 中相应更新。
    返回当前的 context_memory_count。

    :param db: 数据库会话
    :type db: Session
    :param redis: Redis
    :type redis: Redis
    :param user_id: 用户 uuid
    :type user_id: str
    :param conversation_data: 多条对话数据
    :type conversation_data: List[ConversationItem]
    :return: 添加的对话的uuid列表
    :rtype: List[str]
    """
    try:
        user = db.query(User).filter(User.uuid == user_id).first()
        if not user:
            return []

        new_convs = []
        for item in conversation_data:
            # item.timestamp is str, ensure it matches DB requirements
            try:
                ts = datetime.strptime(item.timestamp, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                ts = datetime.now()
            
            meta_data_str = None
            if item.type == 'image':
                try:
                    # Store file path in meta_data as JSON
                    meta_data_str = json.dumps(item.data, ensure_ascii=False)
                except Exception as e:
                    logger.error(f"Failed to serialize meta_data for user {user_id}: {e}")

            conv = Conversation(
                user_id=user_id,
                timestamp=ts,
                source=item.source,
                content=item.content,
                type=item.type,
                meta_data=meta_data_str,
                uuid=item.uuid or str(uuid.uuid4()) # 如果外部没有提供 uuid，则生成一个新的
            )
            db.add(conv)
            new_convs.append({
                "uuid": conv.uuid,
                "timestamp": item.timestamp,
                "source": item.source,
                "content": item.content,
                "type": item.type,
                "meta_data": meta_data_str
            })
        
        user.all_memory_count = (user.all_memory_count or 0) + len(conversation_data)
        user.context_memory_count = (user.context_memory_count or 0) + len(conversation_data)
        
        if commit:
            db.commit()

        # Redis update with Optimistic Locking
        redis_key = f"user_context:{user_id}"
        with redis.pipeline() as pipe:
            for _ in range(3): # Retry up to 3 times
                try:
                    pipe.watch(redis_key)
                    raw_data = pipe.get(redis_key)
                    if raw_data:
                        data = json.loads(raw_data)
                        data["conversations"].extend(new_convs)
                        new_val = json.dumps(data, ensure_ascii=False)
                        
                        pipe.multi()
                        pipe.setex(redis_key, 3600, new_val)
                        pipe.execute()
                    else:
                        pipe.unwatch()
                    break
                except WatchError:
                    continue
        
        return [conv["uuid"] for conv in new_convs]
    except Exception as e:
        logger.error(f"add_conversations error: {e}")
        db.rollback()
        return []


def write_knowledge_buffers(db: Session, redis: Redis, user_id: str, knowledge_contents: List[str], commit: bool = True) -> None:
    """
    更新用户的知识缓存：清空数据库和Redis中该用户旧的知识缓存，并写入新的内容。

    :param db: 数据库会话
    :type db: Session
    :param redis: Redis
    :type redis: Redis
    :param user_id: 用户 uuid
    :type user_id: str
    :param knowledge_contents: 新的知识内容列表
    :type knowledge_contents: List[KnowledgeItem]
    """
    try:
        # 1. 数据库操作：删除旧的，写入新的
        # 删除该用户所有旧的知识缓存
        db.query(KnowledgeBuffer).filter(KnowledgeBuffer.user_id == user_id).delete(synchronize_session=False)

        new_kbs = []
        redis_update_list = []
        
        used_uuid = set()
        for idx, content in enumerate(knowledge_contents):
            kb = KnowledgeBuffer(
                user_id=user_id,
                content=content,
                created_at=datetime.now()
            )
            db.add(kb)
            new_kbs.append(kb)
            redis_update_list.append(content)
        
        if commit:
            db.commit()

        # 2. Redis 操作：直接覆盖
        key = f"user_knowledge:{user_id}"
        new_val = json.dumps(redis_update_list, ensure_ascii=False)
        redis.setex(key, 3600, new_val) # 覆盖并重置过期时间
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        logger.error(f"write_knowledge_buffers error: {e}")
        db.rollback()

def write_memory_update(db: Session, redis: Redis, user_id: str, memory_update: MemoryUpdateCommand, commit: bool = True) -> None:
    # 向数据库中添加记忆更新命令记录
    try:
        cmd_to_dict = {
            "uuid": memory_update.uuid,
            "content": memory_update.content,
            "type": memory_update.type,
        }
        record = MemoryUpdateRecord(
            user_id=user_id,
            update_command=json.dumps(cmd_to_dict, ensure_ascii=False),
            created_at=datetime.now()
        )
        db.add(record)
        if commit:
            db.commit()

        # 更新 Redis 中的最近记忆更新缓存
        recent_update_key = f"user_recent_memory_update:{user_id}"
        raw_data = redis.get(recent_update_key)
        updates_list = []
        if raw_data:
            updates_list = json.loads(raw_data)
        
        updates_list.append(cmd_to_dict)
        # 保持只保存最近10条
        updates_list = updates_list[-10:]
        new_val = json.dumps(updates_list, ensure_ascii=False)
        redis.setex(recent_update_key, 3600, new_val)  # 1小时过期

    except Exception as e:
        logger.error(f"write_recent_memory_update error: {e}")
        db.rollback()
        

def write_used_memory_uuid(redis: Redis, user_id:str, used_uuid: set) -> None:
    try:
        # 直接覆盖
        k = f"user_used_uuid:{user_id}"
        new_val = json.dumps(list(used_uuid), ensure_ascii=False)
        redis.setex(k, 3600, new_val)
    except Exception as e:
        logger.error(f"write_used_memory_uuid error: {e}")


def update_user_nickname(db: Session, redis: Redis, user_id: str, new_nickname: str, commit: bool = True) -> None:
    """
    更新用户昵称，同时在 Redis 中相应更新。

    :param db: 数据库会话
    :type db: Session
    :param redis: Redis
    :type redis: Redis
    :param user_id: 用户 uuid
    :type user_id: str
    :param new_nickname: 新的昵称
    :type new_nickname: str
    """
    try:
        user = db.query(User).filter(User.uuid == user_id).first()
        if user:
            user.nickname = new_nickname
            if commit:
                db.commit()

            # 更新 Redis 中的昵称缓存（如果有的话）
            redis_key = f"user_nickname:{user_id}"
            redis.setex(redis_key, 3600, new_nickname)
    except Exception as e:
        logger.error(f"update_user_nickname error: {e}")
        db.rollback()


def preserve_knowledge_buffers(db: Session, redis: Redis, user_id: str, knowledge_uuids: List[str], commit: bool = True):
    """
    在数据库中删除知识缓存记录，只保留给定uuid的知识缓存。同时在 Redis 中相应更新。

    :param db: 数据库会话
    :type db: Session
    :param redis: Redis
    :type redis: Redis
    :param user_id: 用户 uuid
    :type user_id: str
    :param knowledge_uuids: 多条知识内容对应的 uuid 列表
    :type knowledge_uuids: List[str]
    """
    raise NotImplementedError("preserve_knowledge_buffers is not implemented yet.")
    try:

        db.query(KnowledgeBuffer).filter(
            KnowledgeBuffer.user_id == user_id,
            KnowledgeBuffer.uuid.in_(knowledge_uuids)
        ).delete(synchronize_session=False)
        db.commit()

        key = f"user_knowledge:{user_id}"
        with redis.pipeline() as pipe:
            for _ in range(3):
                try:
                    pipe.watch(key)
                    raw = pipe.get(key)
                    if raw:
                        current_list = json.loads(raw)
                        new_list = [x for x in current_list if x in knowledge_uuids]
                        new_val = json.dumps(new_list, ensure_ascii=False)
                        
                        pipe.multi()
                        pipe.setex(key, 3600, new_val)
                        pipe.execute()
                    else:
                        pipe.unwatch()
                    break
                except WatchError:
                    continue
    except Exception as e:
        logger.error(f"preserve_knowledge_buffers error: {e}")
        db.rollback()


def update_context_summary(db: Session, redis: Redis, user_id: str, new_summary: str, new_context_memory_count: int, commit: bool = True):
    """
    更新用户的上下文总结 summary，同时重置 context_memory_count。
    在 Redis 中相应更新。

    :param db: 数据库会话
    :type db: Session
    :param redis: Redis
    :type redis: Redis
    :param user_id: 用户 uuid
    :type user_id: str
    :param new_summary: 新的上下文总结
    :type new_summary: str
    :param new_context_memory_count: 新的上下文记忆数量
    :type new_context_memory_count: int
    """
    try:
        user = db.query(User).filter(User.uuid == user_id).first()
        if user:
            user.context_summary = new_summary
            user.context_memory_count = new_context_memory_count
            if commit:
                db.commit()

            redis_key = f"user_context:{user_id}"
            with redis.pipeline() as pipe:
                for _ in range(3):
                    try:
                        pipe.watch(redis_key)
                        raw = pipe.get(redis_key)
                        if raw:
                            data = json.loads(raw)
                            data["summary"] = new_summary
                            
                            # Trim conversations to keep only the last new_context_memory_count items
                            convs = data.get("conversations", [])
                            if new_context_memory_count > 0:
                                data["conversations"] = convs[-new_context_memory_count:]
                            else:
                                data["conversations"] = []

                            new_val = json.dumps(data, ensure_ascii=False)
                            
                            pipe.multi()
                            pipe.setex(redis_key, 3600, new_val)
                            pipe.execute()
                        else:
                            pipe.unwatch()
                        break
                    except WatchError:
                        continue
    except Exception as e:
        logger.error(f"update_context_summary error: {e}")
        db.rollback()


def get_context_from_buffer(db: Session, redis: Redis, user_id: str) -> List[Dict[str, Any]]:
    """
    优先从 Redis 获取上下文，如果不存在则调用 prefill_buffer 加载
    """
    redis_key = f"user_context:{user_id}"
    raw_data = redis.get(redis_key)
    
    if raw_data:
        return json.loads(raw_data)
    
    # 尝试预加载
    if prefill_buffer(db, redis, user_id):
        raw_data = redis.get(redis_key)
        if raw_data:
            return json.loads(raw_data)
    
    return []

def get_knowledge_from_buffer(db: Session, redis: Redis, user_id: str) -> List[str]:
    """
    优先从 Redis 获取知识缓存，如果不存在则调用 prefill_buffer 加载
    """
    redis_key = f"user_knowledge:{user_id}"
    raw_data = redis.get(redis_key)
    
    if raw_data:
        raw_list = json.loads(raw_data)
        return raw_list
    
    # 尝试预加载
    if prefill_buffer(db, redis, user_id):
        raw_data = redis.get(redis_key)
        if raw_data:
            raw_list = json.loads(raw_data)
            return raw_list
    
    return []


def get_history_from_db(db: Session, user_id: str, start: int, end: int) -> List[ConversationItem]:
    """
    从数据库获取历史对话，按时间顺序排列 (Oldest first)，匹配之前基于文件的索引逻辑 (0 is oldest)
    :param start: inclusive index (0-based)
    :param end: exclusive index
    """
    limit = end - start
    if limit <= 0:
        return []
        
    conversations = (
        db.query(Conversation)
        .filter(Conversation.user_id == user_id)
        .order_by(Conversation.timestamp.asc())
        .offset(start)
        .limit(limit)
        .all()
    )
    
    result = []
    for conv in conversations:
        result.append(ConversationItem(
            timestamp=conv.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            source=conv.source,
            content=conv.content,
            type=conv.type,
            data=conv.meta_data and json.loads(conv.meta_data) or None,
            uuid=conv.uuid
        ))
    
    return result


def get_total_conversation_count(db: Session, user_id: str) -> int:
    """获取用户历史对话总数"""
    return db.query(Conversation).filter(Conversation.user_id == user_id).count()

def get_context_count(db: Session, user_id: str) -> int:
    """获取用户当前上下文记忆对话数量"""
    user = db.query(User).filter(User.uuid == user_id).first()
    if user and user.context_memory_count:
        return user.context_memory_count
    return 0

def get_user_nickname(db: Session, redis: Redis, user_id: str) -> Optional[str]:
    """
    获取用户昵称
    """
    redis_key = f"user_nickname:{user_id}"
    nickname = redis.get(redis_key)
    print(nickname)
    if nickname:
        return nickname
    
    # 尝试预加载
    if prefill_buffer(db, redis, user_id):
        nickname = redis.get(redis_key)
        if nickname:
            return nickname
    return None

def get_recent_memory_update_from_buffer(db:Session, redis: Redis, user_id: str) -> List[MemoryUpdateCommand]:
    redis_key = f"user_recent_memory_update:{user_id}"
    raw_data = redis.get(redis_key)
    if not raw_data:
        # 尝试预加载
        prefill_buffer(db, redis, user_id)
        raw_data = redis.get(redis_key)

    if raw_data:
        updates_list = json.loads(raw_data)
        result = []
        for item in updates_list:
            result.append(MemoryUpdateCommand(
                uuid=item.get("uuid"),
                content=item.get("content"),
                type=item.get("type")
            ))
        return result
    return []

def get_used_memory_uuid(db:Session, redis: Redis, user_id: str) -> List[str]:
    redis_key = f"user_used_uuid:{user_id}"
    raw_data = redis.get(redis_key)

    if raw_data:
        used_uuid = json.loads(raw_data)
        return used_uuid
    return []

def get_image_server_path(db: Session, user_id: str, uuid: str) -> Optional[str]:
    conv = db.query(Conversation).filter(
        Conversation.user_id == user_id,
        Conversation.uuid == uuid,
        Conversation.type == "image"
    ).first()

    if conv and conv.meta_data:
        try:
            meta_data = json.loads(conv.meta_data)
            return meta_data.get("image_server_path")
        except Exception as e:
            logger.error(f"Failed to parse meta_data for conversation {uuid} of user {user_id}: {e}")
            return None
    return None

def update_image_client_path(db: Session, user_id: str, uuid: str, new_client_path: str) -> bool:
    conv = db.query(Conversation).filter(
        Conversation.user_id == user_id,
        Conversation.uuid == uuid,
        Conversation.type == "image"
    ).first()

    if conv and conv.meta_data:
        try:
            meta_data = json.loads(conv.meta_data)
            meta_data["image_client_path"] = new_client_path
            conv.meta_data = json.dumps(meta_data, ensure_ascii=False)
            db.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to update image client path for conversation {uuid} of user {user_id}: {e}")
            db.rollback()
            return False
    logger.warning(f"Conversation with uuid {uuid} not found for user {user_id} when updating image client path.")
    return False