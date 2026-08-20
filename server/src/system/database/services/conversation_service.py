import json
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from src.domain import ConversationItem
from src.domain.chat import ContextInfo
from src.system.database.redis_buffer import RedisBuffer, WatchError
from src.system.database.sql_database import Conversation, ConversationContext, User
from src.system.database.sql_writer import run_sql_write
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from src.system.database.services.user_store import UserStore


logger = get_logger("database.conversation")


class ConversationService:
    """对话记录、上下文、用户画像/偏好和图片管理。由 DatabaseManager 组合。"""

    def __init__(
        self,
        *,
        sql_session_factory: Callable[[], Any],
        redis_buffer: RedisBuffer,
        user_store: Optional["UserStore"],
    ) -> None:
        self._sql_session_factory = sql_session_factory
        self._redis = redis_buffer
        self.user_store = user_store

    def _new_session(self) -> Any:
        """创建一个新的 SQL 会话；调用者负责关闭。"""
        return self._sql_session_factory()

    def _ensure_redis(self) -> RedisBuffer:
        return self._redis

    @staticmethod
    def _decode_redis_value(value: Any) -> Any:
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return value

    @staticmethod
    def _normalize_preferences(value: Any) -> Dict[str, Any]:
        """把数据库或缓存中的用户偏好统一规范化为字典。"""
        if value is None or value == "":
            return {}
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        while isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                logger.warning(f"Invalid user preferences payload, fallback to empty dict: {value[:80]}")
                return {}
            if parsed == value:
                return {}
            value = parsed
        if isinstance(value, dict):
            return value
        logger.warning(f"Unsupported user preferences payload type: {type(value).__name__}")
        return {}

    @staticmethod
    def _context_redis_key(user_id: str, character_id: str = "luotianyi") -> str:
        return f"user_context:{user_id}:{character_id or 'luotianyi'}"

    def _get_or_create_conversation_context(
        self,
        db: "Session",
        user: User,
        character_id: str = "luotianyi",
    ) -> ConversationContext:
        '''
        兼容性地获取或创建 ConversationContext 对象。若不存在，则创建一个新的 ConversationContext 并返回。
        '''
        character_id = character_id or "luotianyi"
        context = (
            db.query(ConversationContext)
            .filter(
                ConversationContext.user_id == user.uuid,
                ConversationContext.character_id == character_id,
            )
            .first()
        )
        if context is not None:
            return context

        context = ConversationContext(
            user_id=user.uuid,
            character_id=character_id,
            context_summary=(user.context_summary or "") if character_id == "luotianyi" else "",
            context_memory_count=(user.context_memory_count or 0) if character_id == "luotianyi" else 0,
        )
        db.add(context)
        db.flush()
        return context

    @staticmethod
    def _is_context_stale(latest_timestamp: datetime | None, max_age_days: Optional[float]) -> bool:
        if latest_timestamp is None or max_age_days is None or max_age_days <= 0:
            return False
        return (datetime.now() - latest_timestamp).total_seconds() > max_age_days * 24 * 60 * 60

    def _latest_conversation_timestamp(
        self,
        db: "Session",
        user_id: str,
        character_id: str = "luotianyi",
    ) -> datetime | None:
        latest = (
            db.query(Conversation.timestamp)
            .filter(Conversation.user_id == user_id)
            .filter(Conversation.character_id == character_id)
            .order_by(Conversation.timestamp.desc())
            .first()
        )
        return latest[0] if latest else None

    def _clear_conversation_context_in_session(
        self,
        db: "Session",
        user: User,
        character_id: str = "luotianyi",
    ) -> None:
        context = self._get_or_create_conversation_context(db, user, character_id)
        context.context_summary = ""
        context.context_memory_count = 0
        if character_id == "luotianyi":
            user.context_summary = ""
            user.context_memory_count = 0

    def get_user_preferences(self, user_id: str) -> Optional[Dict[str, Any]]:
        '''
        获取用户的聊天偏好设置。返回字典，如果用户不存在则返回 None。
        '''
        if self.user_store is None:
            return None
        return self.user_store.get_user_preferences(user_id)

    def save_user_preferences(self, user_id: str, preferences: Dict[str, Any]) -> bool:
        '''
        更新数据库中的用户聊天偏好设置，并同步更新 Redis 缓存。成功返回 True，失败返回 False。
        '''
        if self.user_store is None:
            return False
        return self.user_store.save_user_preferences(user_id, preferences)

    def update_user_description(self, user_id: str, new_description: str, commit: bool = True) -> None:
        """更新用户画像描述，同时更新 Redis 缓存。"""
        if self.user_store is None:
            return
        self.user_store.update_user_description(user_id, new_description, commit=commit)

    def get_user_description(self, user_id: str) -> Optional[str]:
        """获取用户画像描述。"""
        if self.user_store is None:
            return None
        return self.user_store.get_user_description(user_id)
    
    def get_user_nickname(self, user_id: str) -> Optional[str]:
        """获取用户昵称。"""
        raise NotImplementedError("get_user_nickname is deprecated. Use get_user_description or get_user_preferences instead.")
        redis = self._ensure_redis()
        redis_key = f"user_nickname:{user_id}"
        nickname = redis.get(redis_key)
        if nickname:
            return nickname
        if self.prefill_buffer(user_id):
            nickname = redis.get(redis_key)
            if nickname:
                return nickname
        return None

    def get_user_expression_context_data(self, user_id: str) -> Dict[str, Any]:
        '''
        不该使用
        '''
        raise NotImplementedError("get_user_expression_context_data is deprecated. Use get_user_preferences instead.")
        db = self._new_session()
        try:
            user = db.query(User).filter(User.uuid == user_id).first()
            if not user:
                return {
                    "nickname": "你",
                    "description": "",
                    "preferences": None,
                }
            return {
                "nickname": user.nickname or "你",
                "description": user.description or "",
                "preferences": user.preferences,
            }
        finally:
            db.close()

    def update_user_nickname(self, user_id: str, new_nickname: str, commit: bool = True) -> None:
        raise NotImplementedError("update_user_nickname is deprecated. Use update_user_description or update_user_preferences instead.")
        """更新用户昵称，同时更新 Redis 缓存。"""
        redis = self._ensure_redis()
        db = self._new_session()
        try:
            def _write() -> bool:
                user = db.query(User).filter(User.uuid == user_id).first()
                if not user:
                    return False
                user.nickname = new_nickname
                if commit:
                    db.commit()
                return True

            updated = run_sql_write(_write)
            if updated:
                redis.setex(f"user_nickname:{user_id}", 3600, new_nickname)
        except Exception as e:
            logger.error(f"update_user_nickname error: {e}")
            db.rollback()
        finally:
            db.close()


    def prefill_buffer(
        self,
        user_id: str,
        types: List[str] = ["all"],
        character_id: str = "luotianyi",
    ) -> bool:
        """
        将用户的上下文信息预加载到 Redis 中，提升响应速度。
        """
        redis = self._ensure_redis()
        db = self._new_session()
        try:
            user = db.query(User).filter(User.uuid == user_id).first()
            if not user:
                logger.error(f"User {user_id} not found for prefill_buffer.")
                return False

            # 1. 加载上下文
            if "all" in types or "context" in types:
                context = self._get_or_create_conversation_context(db, user, character_id)
                db.commit()
                summary = context.context_summary or ""
                context_memory_count = context.context_memory_count or 0
                context_conversations = (
                    db.query(Conversation)
                    .filter(Conversation.user_id == user_id)
                    .filter(Conversation.character_id == character_id)
                    .order_by(Conversation.timestamp.desc())
                    .limit(context_memory_count)
                    .all()
                )
                context_info = ContextInfo(
                    summary=summary,
                    conversations=[
                        {
                            "uuid": conv.uuid,
                            "timestamp": conv.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                            "source": conv.source,
                            "content": conv.content,
                            "type": conv.type,
                            "meta_data": json.loads(conv.meta_data) if conv.meta_data else None,
                        }
                        for conv in reversed(context_conversations)
                    ],
                    context_count=context_memory_count,
                )
                redis.setex(self._context_redis_key(user_id, character_id), 3600, context_info)

            # # 2. 加载知识库缓存
            # if "all" in types or "knowledge" in types:
            #     knowledge_buffers = (
            #         db.query(KnowledgeBuffer)
            #         .filter(KnowledgeBuffer.user_id == user_id)
            #         .order_by(KnowledgeBuffer.uuid.asc())
            #         .all()
            #     )
            #     knowledge_contents = [kb.content for kb in knowledge_buffers]
            #     redis.setex(f"user_knowledge:{user_id}", 3600, knowledge_contents)

            # 3. 加载用户偏好
            if "all" in types or "preferences" in types:
                preferences = self._normalize_preferences(user.preferences)
                redis.setex(f"user_preferences:{user_id}", 3600, preferences)

            # 3.1 加载用户画像描述
            if "all" in types or "description" in types:
                description = user.description or ""
                redis.setex(f"user_description:{user_id}", 3600, description)

            logger.info(f"Prefilled buffer for user {user_id} in Redis.")
            return True

        except Exception as e:
            logger.error(f"Error in prefill_buffer for user {user_id}: {e}")
            return False
        finally:
            db.close()

    # ────────────────────────────────────────────
    # 对话记录和记忆管理
    # ────────────────────────────────────────────

    def add_conversations(
        self,
        user_id: str,
        conversation_data: List[ConversationItem],
        commit: bool = True,
        character_id: str = "luotianyi",
    ) -> List[str]:
        """
        在数据库中增加对话记录，同时更新 user 的对话计数。
        在 Redis 中相应更新。
        返回添加的对话的 uuid 列表。
        """
        redis = self._ensure_redis()
        db = self._new_session()
        try:
            def _write() -> List[Dict[str, Any]]:
                user = db.query(User).filter(User.uuid == user_id).first()
                if not user:
                    return []
                context = self._get_or_create_conversation_context(db, user, character_id)
                new_convs_local: List[Dict[str, Any]] = []
                for item in conversation_data:
                    try:
                        ts = datetime.strptime(item.timestamp, "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        ts = datetime.now()

                    meta_data_str = None
                    if item.data is not None:
                        try:
                            meta_data_str = json.dumps(item.data, ensure_ascii=False)
                        except Exception as e:
                            logger.error(f"Failed to serialize meta_data for user {user_id}: {e}")

                    conv = Conversation(
                        user_id=user_id,
                        character_id=character_id,
                        timestamp=ts,
                        source=item.source,
                        content=item.content,
                        type=item.type,
                        meta_data=meta_data_str,
                        uuid=item.uuid or str(uuid.uuid4()),
                    )
                    db.add(conv)
                    new_convs_local.append({
                        "uuid": conv.uuid,
                        "timestamp": item.timestamp,
                        "source": item.source,
                        "content": item.content,
                        "type": item.type,
                        "meta_data": meta_data_str,
                    })

                user.all_memory_count = (user.all_memory_count or 0) + len(conversation_data)
                context.context_memory_count = (context.context_memory_count or 0) + len(conversation_data)
                if character_id == "luotianyi":
                    user.context_memory_count = context.context_memory_count
                if commit:
                    db.commit()
                return new_convs_local

            new_convs = run_sql_write(_write)

            # 更新 Redis
            redis_key = self._context_redis_key(user_id, character_id)
            with redis.pipeline() as pipe:
                for _ in range(3):
                    try:
                        pipe.watch(redis_key)
                        raw_data: ContextInfo = self._decode_redis_value(pipe.get(redis_key))
                        if raw_data:
                            raw_data.conversations.extend(new_convs)
                            pipe.multi()
                            pipe.setex(redis_key, 3600, raw_data)
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
        finally:
            db.close()


    def compact_conversation_context(
        self,
        user_id: str,
        new_summary: str,
        keep_recent_count: int,
        expected_context_count: Optional[int] = None,
        character_id: str = "luotianyi",
        commit: bool = True,
    ) -> bool:
        """更新上下文总结，并保留最近 keep_recent_count 条未压缩对话。"""
        redis = self._ensure_redis()
        db = self._new_session()
        try:
            def _write() -> Optional[int]:
                user = db.query(User).filter(User.uuid == user_id).first()
                if not user:
                    return None
                context = self._get_or_create_conversation_context(db, user, character_id)
                current_context_count = context.context_memory_count or 0
                retained_context_count = keep_recent_count
                if expected_context_count is not None:
                    if current_context_count < expected_context_count:
                        return None
                    retained_context_count += current_context_count - expected_context_count
                context.context_summary = new_summary
                context.context_memory_count = retained_context_count
                if character_id == "luotianyi":
                    user.context_summary = new_summary
                    user.context_memory_count = retained_context_count
                if commit:
                    db.commit()
                return retained_context_count

            retained_context_count = run_sql_write(_write)

            if retained_context_count is not None:
                redis_key = self._context_redis_key(user_id, character_id)
                with redis.pipeline() as pipe:
                    for _ in range(3):
                        try:
                            pipe.watch(redis_key)
                            data: ContextInfo = self._decode_redis_value(pipe.get(redis_key))
                            if data:
                                data.summary = new_summary
                                convs = data.conversations
                                if retained_context_count > 0:
                                    data.conversations = convs[-retained_context_count:]
                                else:
                                    data.conversations = []
                                data.context_count = retained_context_count
                                pipe.multi()
                                pipe.setex(redis_key, 3600, data)
                                pipe.execute()
                            else:
                                pipe.unwatch()
                            break
                        except WatchError:
                            continue
            return retained_context_count is not None
        except Exception as e:
            logger.error(f"compact_conversation_context error: {e}")
            db.rollback()
            return False
        finally:
            db.close()

    def reset_conversation_context_if_stale(
        self,
        user_id: str,
        character_id: str = "luotianyi",
        max_context_age_days: Optional[float] = None,
    ) -> bool:
        """Clear runtime context when the latest message is older than max_context_age_days."""
        if max_context_age_days is None or max_context_age_days <= 0:
            return False

        redis = self._ensure_redis()
        db = self._new_session()
        try:
            def _write() -> bool:
                user = db.query(User).filter(User.uuid == user_id).first()
                if not user:
                    return False
                latest_timestamp = self._latest_conversation_timestamp(db, user_id, character_id)
                if not self._is_context_stale(latest_timestamp, max_context_age_days):
                    return False
                self._clear_conversation_context_in_session(db, user, character_id)
                db.commit()
                return True

            cleared = run_sql_write(_write)
            if cleared:
                redis.setex(
                    self._context_redis_key(user_id, character_id),
                    3600,
                    ContextInfo(summary="", conversations=[], context_count=0),
                )
            return bool(cleared)
        except Exception as e:
            logger.error(f"reset_conversation_context_if_stale error: {e}")
            db.rollback()
            return False
        finally:
            db.close()

    def _get_context_from_buffer(
        self,
        user_id: str,
        character_id: str = "luotianyi",
    ) -> ContextInfo:
        """优先从 Redis 获取上下文，不存在则调用 prefill_buffer 加载。"""
        redis = self._ensure_redis()
        redis_key = self._context_redis_key(user_id, character_id)
        data: Optional[ContextInfo] = self._decode_redis_value(redis.get(redis_key))
        if data:
            return data

        if self.prefill_buffer(user_id, character_id=character_id):
            data = self._decode_redis_value(redis.get(redis_key))
            if data:
                return data
        return []

    def get_conversation_context_state(
        self,
        user_id: str,
        character_id: str = "luotianyi",
    ) -> Dict[str, Any]:
        """获取对话运行上下文的结构化状态。"""
        context_data: ContextInfo = self._get_context_from_buffer(
            user_id,
            character_id=character_id,
        )
        if not context_data:
            return {
                "summary": "",
                "conversations": [],
                "context_count": 0,
                "version": "0:0:",
            }

        conversations = context_data.conversations or []
        if context_data.context_count is not None:
            context_count = context_data.context_count
        else:
            context_count = self.get_context_count(user_id, character_id=character_id)
        last_uuid = conversations[-1].get("uuid", "") if conversations else ""
        return {
            "summary": context_data.summary or "",
            "conversations": conversations,
            "context_count": context_count,
            "version": f"{context_count}:{len(conversations)}:{last_uuid}",
        }

    def get_history_from_db(
        self,
        user_id: str,
        start: int,
        end: int,
        character_id: Optional[str] = None,
    ) -> List[ConversationItem]:
        """从数据库获取指定范围的历史对话，按时间顺序排列 (0 is oldest)。"""
        limit = end - start
        if limit <= 0:
            return []

        db = self._new_session()
        try:
            query = (
                db.query(Conversation)
                .filter(Conversation.user_id == user_id)
            )
            if character_id is not None:
                query = query.filter(Conversation.character_id == character_id)
            conversations = query.order_by(Conversation.timestamp.asc()).offset(start).limit(limit).all()
            result = []
            for conv in conversations:
                result.append(ConversationItem(
                    timestamp=conv.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                    source=conv.source,
                    content=conv.content,
                    type=conv.type,
                    data=conv.meta_data and json.loads(conv.meta_data) or None,
                    uuid=conv.uuid,
                ))
            return result
        finally:
            db.close()

    def get_total_conversation_count(self, user_id: str, character_id: Optional[str] = None) -> int:
        """获取用户历史对话总数。"""
        db = self._new_session()
        try:
            query = db.query(Conversation).filter(Conversation.user_id == user_id)
            if character_id is not None:
                query = query.filter(Conversation.character_id == character_id)
            return query.count()
        finally:
            db.close()

    def get_context_count(self, user_id: str, character_id: str = "luotianyi") -> int:
        """获取用户当前上下文记忆对话数量。"""
        db = self._new_session()
        redis = self._ensure_redis()
        context_info: Optional[ContextInfo] = self._decode_redis_value(redis.get(self._context_redis_key(user_id, character_id)))
        if context_info and context_info.context_count is not None:
            return context_info.context_count

        # 如果 Redis 中没有缓存，则从数据库中获取 context_memory_count
        try:
            user = db.query(User).filter(User.uuid == user_id).first()
            if user:
                context = self._get_or_create_conversation_context(db, user, character_id)
                db.commit()
                return context.context_memory_count or 0
            return 0
        finally:
            db.close()

    
    
    # ————————
    # 图片管理
    # ————————


    def get_image_server_path(self, user_id: str, conv_uuid: str) -> Optional[str]:
        """获取图片的服务器路径。"""
        db = self._new_session()
        try:
            conv = db.query(Conversation).filter(
                Conversation.user_id == user_id,
                Conversation.uuid == conv_uuid,
                Conversation.type == "image",
            ).first()

            if conv and conv.meta_data:
                try:
                    meta_data = json.loads(conv.meta_data)
                    return meta_data.get("image_server_path")
                except Exception as e:
                    logger.error(f"Failed to parse meta_data for conversation {conv_uuid}: {e}")
            return None
        finally:
            db.close()

    def update_image_client_path(self, user_id: str, conv_uuid: str, new_client_path: str) -> bool:
        """更新图片的客户端路径。"""
        db = self._new_session()
        try:
            def _write() -> bool:
                conv = db.query(Conversation).filter(
                    Conversation.user_id == user_id,
                    Conversation.uuid == conv_uuid,
                    Conversation.type == "image",
                ).first()

                if conv and conv.meta_data:
                    meta_data = json.loads(conv.meta_data)
                    meta_data["image_client_path"] = new_client_path
                    conv.meta_data = json.dumps(meta_data, ensure_ascii=False)
                    db.commit()
                    return True
                return False

            success = run_sql_write(_write)
            if not success:
                logger.warning(f"Conversation with uuid {conv_uuid} not found for user {user_id} when updating image client path.")
            return success
        except Exception as e:
            logger.error(f"Failed to update image client path for conversation {conv_uuid}: {e}")
            db.rollback()
            return False
        finally:
            db.close()
