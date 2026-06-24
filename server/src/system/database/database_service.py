import os
import hmac
import bcrypt
from jose import jwt
import json
from typing import Dict, Any, Optional, List, Tuple, TYPE_CHECKING
from datetime import datetime
import uuid
from src.utils.logger import get_logger

from src.domain import ConversationItem
from src.system.database.sql_database import init_sql_db, get_sql_session, SessionLocal
from src.system.database.sql_database import (User,InviteCode,Conversation)
from src.system.database.redis_buffer import RedisBuffer, WatchError, init_redis_buffer, get_redis_buffer
from src.system.database.sql_writer import run_sql_write
from src.system.database.event_store import EventStore
from src.system.database.memory_store import MemoryStore

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from src.utils.llm_service import LLMService


logger = get_logger("database")

JWT_SECRET_ENV = "JWT_SECRET"
JWT_SECRET = os.environ.get(JWT_SECRET_ENV)
ALGORITHM = "HS256"

_BCRYPT_PREFIXES = ("$2a$", "$2b$", "$2y$")
_BCRYPT_ROUNDS = 12


def _is_bcrypt_hash(value: str | None) -> bool:
    return bool(value and value.startswith(_BCRYPT_PREFIXES))


def _hash_password(password: str) -> str:
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS))
    return hashed.decode("utf-8")


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
    except ValueError:
        return False


# ============================================================================
# DatabaseManager — 封装数据库操作，内部持有 redis 实例并自行管理 Session
# ============================================================================

class DatabaseManager:
    """
    数据库管理器，封装所有数据库操作。

    - 内部持有 RedisBuffer (redis) 实例
    - 每个方法自行创建 SessionLocal() 并通过 try/finally 确保关闭
    - 不再要求调用者传入 db 和 redis 参数
    """

    def __init__(self, config: Optional[Dict[str, Any]]) -> None:
        self.config = config or {}
        self._redis: Optional[RedisBuffer] = None
        self.event_store: Optional[EventStore] = None
        self.memory_store: Optional[MemoryStore] = None
        self.init_all_databases()

    def init_all_databases(self) -> None:
        """初始化所有数据库组件（SQL/Redis 缓存）。"""
        try:
            init_sql_db(
                self.config.get("sql_db_folder", "data/database"),
                self.config.get("sql_db_file", "luotianyi.db"),
            )
            init_redis_buffer(self.config.get("redis", {}))

            self.event_store = EventStore(config = self.config.get("event_store", {}), sql_session_factory=self.open_sql_session, redis_buffer=self._ensure_redis)
            self.memory_store = MemoryStore(config = self.config.get("memory_store", {}), sql_session_factory=self.open_sql_session, redis_buffer=self._ensure_redis)
            logger.info("Main database initialized successfully.")
        except Exception as e:
            logger.error(f"Error initializing databases: {e}")
            raise

    def create_llm_modules(self, llm_service: "LLMService") -> None:
        if self.event_store is not None:
            self.event_store.create_llm_module(llm_service)
        if self.memory_store is not None:
            self.memory_store.create_llm_module(llm_service)

    # ── 内部工具 ─────────────────────────────────────────────

    def _ensure_redis(self) -> RedisBuffer:
        if self._redis is None:
            # 自动从 get_redis_buffer 获取已初始化的实例
            self._redis = get_redis_buffer()
        return self._redis

    def _new_session(self) -> Session:
        """创建一个新的 SQL 会话。调用者负责关闭。"""
        try:
            return get_sql_session()
        except Exception:
            # fallback: 如果 sql db 还未初始化，尝试直接使用 SessionLocal
            if SessionLocal is not None:
                return SessionLocal()
            raise

    def open_sql_session(self) -> Session:
        """Compatibility factory for legacy components not yet using manager methods."""
        return self._new_session()

    @staticmethod
    def init_all(config: Dict[str, Any]) -> None:
        """初始化主数据库组件（SQL/Redis 缓存）。"""
        try:
            init_sql_db(config.get("sql_db_folder", "data/database"), config.get("sql_db_file", "luotianyi.db"))
            init_redis_buffer(config.get("redis", {}))
            logger.info("Main database initialized successfully.")
        except Exception as e:
            logger.error(f"Error initializing databases: {e}")
            raise

    # ── 公共方法 ─────────────────────────────────────────────

    def get_user_uuid_by_username(self, username: str) -> Optional[str]:
        '''
        根据用户名获取用户 UUID。会使用 Redis 缓存，缓存键为 user_id:{username}。如果缓存未命中，会从数据库查询并更新缓存。
        '''
        # 先尝试从 Redis 缓存获取，缓存键为 user_id:{username}
        redis = self._ensure_redis()
        cached_uuid = redis.get(f"user_id:{username}")
        if cached_uuid:
            return cached_uuid
        
        # 缓存未命中，从数据库查询并更新缓存
        db = self._new_session()
        try:
            user = db.query(User).filter_by(username=username).first()
            if user:
                # 更新缓存
                redis.setex(f"user_id:{username}", 3600, user.uuid)
                return user.uuid
            return None
        finally:
            db.close()

    # ────────────────────────────────────────────
    # Token 管理， 包括登录 token 和消息 token
    # ────────────────────────────────────────────

    def check_auth_token(self, username: str, token: str) -> bool:
        db = self._new_session()
        try:
            user = db.query(User).filter_by(username=username).first()
            return bool(user and user.auth_token == token)
        finally:
            db.close()

    def update_auth_token(self, username: str) -> Optional[str]:
        db = self._new_session()
        try:
            new_token = str(uuid.uuid4())
            user = db.query(User).filter_by(username=username).first()
            if not user:
                return None
            user.auth_token = new_token
            db.commit()
            return new_token
        except Exception as e:
            logger.error(f"Error updating auth token for {username}: {e}")
            db.rollback()
            return None
        finally:
            db.close()

    def generate_message_token(self, username: str) -> Optional[str]:
        if not JWT_SECRET:
            logger.error("JWT_SECRET is not set. Cannot generate message token.")
            return None
        db = self._new_session()
        try:
            user = db.query(User).filter_by(username=username).first()
            if not user:
                return None
            message_token = jwt.encode({"user_uuid": user.uuid}, JWT_SECRET, algorithm=ALGORITHM)
            redis = self._ensure_redis()
            redis.setex(f"user_message_token:{user.uuid}", 3600, message_token)
            return message_token
        finally:
            db.close()

    def decode_message_token(self, token: str) -> Optional[str]:
        if not JWT_SECRET:
            logger.error("JWT_SECRET is not set. Cannot decode message token.")
            return None
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
            return payload.get("user_uuid")
        except jwt.JWTError:
            return None

    def check_message_token(self, username: str, token: str) -> Tuple[bool, Optional[str]]:
        '''
        检查消息 token 是否有效。
        '''
        user_uuid = self.get_user_uuid_by_username(username)  # 确保缓存更新
        if not user_uuid:
            return False, None
        decoded_uuid = self.decode_message_token(token)
        if decoded_uuid == user_uuid:
            return True, user_uuid
        return False, None
    
    # ────────────────────────────────────────────
    # 用户注册、登录、重置账户相关方法
    # ────────────────────────────────────────────

    def register_user(self, username: str, password: str, invite_code_str: str) -> Tuple[bool, str]:
        '''
        注册新用户，使用邀请码机制。检查邀请码是否存在和被使用。成功注册后，邀请码标记为已使用。
        成功返回 (True, "注册成功")，失败返回 (False, "失败原因")。
        '''
        db = self._new_session()
        try:
            code = db.query(InviteCode).filter_by(code=invite_code_str).first()
            if not code:
                logger.info(f"Register failed: invalid invite code for username={username}")
                return False, "注册失败，请检查邀请码或用户名"
            if code.is_used:
                logger.info(f"Register failed: invite code already used for username={username}")
                return False, "注册失败，请检查邀请码或用户名"

            existing_user = db.query(User).filter_by(username=username).first()
            if existing_user:
                logger.info(f"Register failed: username already exists: {username}")
                return False, "注册失败，请检查邀请码或用户名"

            new_user = User(username=username, password=_hash_password(password))
            db.add(new_user)
            db.flush()

            code.is_used = True
            code.used_at = datetime.now(tz=None)
            code.user_id = new_user.uuid

            db.commit()
            return True, "注册成功"
        except Exception as e:
            logger.error(f"Error registering user {username}: {e}")
            db.rollback()
            return False, "注册失败，请检查邀请码或用户名"
        finally:
            db.close()

    def verify_user(self, username: str, password: str) -> bool:
        '''
        验证用户的用户名和密码。支持自动升级旧密码哈希。成功返回 True，失败返回 False。
        '''
        db = self._new_session()
        try:
            user = db.query(User).filter_by(username=username).first()
            if not user or not user.password:
                return False

            stored = user.password
            if _is_bcrypt_hash(stored):
                return _verify_password(password, stored)

            if hmac.compare_digest(stored, password):
                user.password = _hash_password(password)
                db.commit()
                return True
            return False
        except Exception as e:
            logger.error(f"Error verifying user {username}: {e}")
            db.rollback()
            return False
        finally:
            db.close()

    def reset_account(self, invite_code_str: str, new_username: str, new_password: str) -> Tuple[bool, str]:
        '''
        使用邀请码重置账户（更改用户名和密码）。成功返回 (True, "重置成功")，失败返回 (False, "失败原因")。
        '''
        db = self._new_session()
        try:
            code = db.query(InviteCode).filter_by(code=invite_code_str).first()
            if not code:
                return False, "邀请码无效"
            if not code.is_used or not code.user_id:
                return False, "邀请码尚未被使用，无法重置"

            user = db.query(User).filter_by(uuid=code.user_id).first()
            if not user:
                return False, "邀请码关联的用户不存在"

            existing = (
                db.query(User)
                .filter(User.username == new_username, User.uuid != user.uuid)
                .first()
            )
            if existing:
                return False, "新用户名已被其他用户使用"

            old_username = user.username
            user.username = new_username
            user.password = _hash_password(new_password)
            user.auth_token = None
            db.commit()
            logger.info(
                f"Account reset: invite_code={invite_code_str}, "
                f"old_username={old_username}, new_username={new_username}"
            )
            return True, "重置成功"
        except Exception as e:
            logger.error(f"Error resetting account for invite_code={invite_code_str}: {e}")
            db.rollback()
            return False, "重置失败"
        finally:
            db.close()


    def authenticate_password_login(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        if not self.verify_user(username, password):
            return None
        user_uuid = self.get_user_uuid_by_username(username)
        if user_uuid is None:
            return None
        login_token = self.update_auth_token(username)
        message_token = self.generate_message_token(username)
        elapsed = self.update_login_time(user_uuid)
        return {
            "user_uuid": user_uuid,
            "login_token": login_token,
            "message_token": message_token,
            "elapsed_from_last_login": elapsed,
        }

    def authenticate_auto_login(self, username: str, token: str) -> Optional[Dict[str, Any]]:
        if not self.check_auth_token(username, token):
            return None
        user_uuid = self.get_user_uuid_by_username(username)
        if user_uuid is None:
            return None
        login_token = self.update_auth_token(username)
        message_token = self.generate_message_token(username)
        elapsed = self.update_login_time(user_uuid)
        return {
            "user_uuid": user_uuid,
            "login_token": login_token,
            "message_token": message_token,
            "elapsed_from_last_login": elapsed,
        }
    
    def update_login_time(self, user_id: str) -> Optional[float]:
        """
        将用户的最新登录时间更新为当前时间，返回距离上次登录的时间差（秒）。
        如果是第一次登录，返回 None。
        """
        db = self._new_session()
        try:
            user = db.query(User).filter(User.uuid == user_id).first()
            if not user:
                logger.error(f"User {user_id} not found for update_login_time.")
                return None

            now = datetime.now()
            last_login_time = user.last_login
            user.last_login = now
            db.commit()

            if last_login_time:
                return (now - last_login_time).total_seconds()
            return None
        except Exception as e:
            logger.error(f"Error updating login time for user {user_id}: {e}")
            db.rollback()
            return None
        finally:
            db.close()
    
    # ────────────────────────────────────────────
    # 用户长期偏好设置管理
    # ────────────────────────────────────────────

    def get_user_preferences(self, user_id: str) -> Optional[Dict[str, Any]]:
        '''
        获取用户的聊天偏好设置。返回字典，如果用户不存在则返回 None。
        '''
        # 先尝试从 Redis 缓存获取
        redis = self._ensure_redis()
        cached_preferences = redis.get(f"user_preferences:{user_id}")
        if cached_preferences:
            return cached_preferences

        # 若缓存未命中，从数据库查询并更新缓存
        db = self._new_session()
        try:
            user = db.query(User).filter_by(uuid=user_id).first()
            if not user:
                return None
            preferences = json.loads(user.preferences) if user.preferences else {}
            # 更新缓存
            redis.setex(f"user_preferences:{user_id}", 3600, preferences) # 注意自己实现的redis支持所有类型
            return preferences
        finally:
            db.close()

    def save_user_preferences(self, user_id: str, preferences: Dict[str, Any]) -> bool:
        '''
        更新数据库中的用户聊天偏好设置，并同步更新 Redis 缓存。成功返回 True，失败返回 False。
        '''
        db = self._new_session()
        redis = self._ensure_redis()
        try:
            user = db.query(User).filter_by(uuid=user_id).first()
            if not user:
                return False
            user.preferences = json.dumps(preferences, ensure_ascii=False)
            db.commit()
            # 更新 Redis 缓存
            redis.setex(f"user_preferences:{user_id}", 3600, preferences)
            return True
        except Exception as e:
            logger.error(f"Failed to save preferences for user {user_id}: {e}")
            db.rollback()
            return False
        finally:
            db.close()

    def update_user_description(self, user_id: str, new_description: str, commit: bool = True) -> None:
        """更新用户画像描述，同时更新 Redis 缓存。"""
        redis = self._ensure_redis()
        db = self._new_session()
        try:
            def _write() -> bool:
                user = db.query(User).filter(User.uuid == user_id).first()
                if not user:
                    return False
                user.description = new_description
                if commit:
                    db.commit()
                return True

            updated = run_sql_write(_write)
            if updated:
                redis.setex(f"user_description:{user_id}", 3600, new_description)
        except Exception as e:
            logger.error(f"update_user_description error: {e}")
            db.rollback()
        finally:
            db.close()

    def get_user_description(self, user_id: str) -> Optional[str]:
        """获取用户画像描述。"""
        redis = self._ensure_redis()
        redis_key = f"user_description:{user_id}"
        description = redis.get(redis_key)
        if description is not None:
            return description
        if self.prefill_buffer(user_id, types=["description"]):
            description = redis.get(redis_key)
            if description is not None:
                return description
        return None
    
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


    def prefill_buffer(self, user_id: str, types: List[str] = ["all"]) -> bool:
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
                summary = user.context_summary or ""
                context_memory_count = user.context_memory_count or 0
                context_conversations = (
                    db.query(Conversation)
                    .filter(Conversation.user_id == user_id)
                    .order_by(Conversation.timestamp.desc())
                    .limit(context_memory_count)
                    .all()
                )
                context_info = {
                    "summary": summary,
                    "conversations": [
                        {
                            "timestamp": conv.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                            "source": conv.source,
                            "content": conv.content,
                            "type": conv.type,
                        }
                        for conv in reversed(context_conversations)
                    ],
                }
                redis.setex(f"user_context:{user_id}", 3600, context_info)

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
                preferences = user.preferences or {}
                redis.setex(f"user_preferences:{user_id}", 3600, json.dumps(preferences))

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

    def add_conversations(self, user_id: str, conversation_data: List[ConversationItem], commit: bool = True) -> List[str]:
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

                new_convs_local: List[Dict[str, Any]] = []
                for item in conversation_data:
                    try:
                        ts = datetime.strptime(item.timestamp, "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        ts = datetime.now()

                    meta_data_str = None
                    if item.type == "image":
                        try:
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
                user.context_memory_count = (user.context_memory_count or 0) + len(conversation_data)
                if commit:
                    db.commit()
                return new_convs_local

            new_convs = run_sql_write(_write)

            # 更新 Redis
            redis_key = f"user_context:{user_id}"
            with redis.pipeline() as pipe:
                for _ in range(3):
                    try:
                        pipe.watch(redis_key)
                        raw_data = pipe.get(redis_key)
                        if raw_data:
                            raw_data["conversations"].extend(new_convs)
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


    def update_context_summary(self, user_id: str, new_summary: str, new_context_memory_count: int, commit: bool = True) -> None:
        """更新用户的上下文总结 summary，重置 context_memory_count，同步更新 Redis。"""
        redis = self._ensure_redis()
        db = self._new_session()
        try:
            def _write() -> bool:
                user = db.query(User).filter(User.uuid == user_id).first()
                if not user:
                    return False
                user.context_summary = new_summary
                user.context_memory_count = new_context_memory_count
                if commit:
                    db.commit()
                return True

            updated = run_sql_write(_write)

            if updated:
                redis_key = f"user_context:{user_id}"
                with redis.pipeline() as pipe:
                    for _ in range(3):
                        try:
                            pipe.watch(redis_key)
                            data = pipe.get(redis_key)
                            if data:
                                data["summary"] = new_summary
                                convs = data.get("conversations", [])
                                if new_context_memory_count > 0:
                                    data["conversations"] = convs[-new_context_memory_count:]
                                else:
                                    data["conversations"] = []
                                pipe.multi()
                                pipe.setex(redis_key, 3600, data)
                                pipe.execute()
                            else:
                                pipe.unwatch()
                            break
                        except WatchError:
                            continue
        except Exception as e:
            logger.error(f"update_context_summary error: {e}")
            db.rollback()
        finally:
            db.close()

    def get_context_from_buffer(self, user_id: str) -> Any:
        """优先从 Redis 获取上下文，不存在则调用 prefill_buffer 加载。"""
        redis = self._ensure_redis()
        redis_key = f"user_context:{user_id}"
        data = redis.get(redis_key)
        if data:
            return data

        if self.prefill_buffer(user_id):
            data = redis.get(redis_key)
            if data:
                return json.loads(data)
        return []

    def get_history_from_db(self, user_id: str, start: int, end: int) -> List[ConversationItem]:
        """从数据库获取指定范围的历史对话，按时间顺序排列 (0 is oldest)。"""
        limit = end - start
        if limit <= 0:
            return []

        db = self._new_session()
        try:
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
                    uuid=conv.uuid,
                ))
            return result
        finally:
            db.close()

    def get_total_conversation_count(self, user_id: str) -> int:
        """获取用户历史对话总数。"""
        db = self._new_session()
        try:
            return db.query(Conversation).filter(Conversation.user_id == user_id).count()
        finally:
            db.close()

    def get_context_count(self, user_id: str) -> int:
        """获取用户当前上下文记忆对话数量。"""
        db = self._new_session()
        try:
            user = db.query(User).filter(User.uuid == user_id).first()
            if user and user.context_memory_count:
                return user.context_memory_count
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

    @property
    def redis(self) -> RedisBuffer:
        """便捷属性：直接访问 Redis 实例。"""
        return self._ensure_redis()
    
    def get_sql_session(self) -> Session:
        """便捷属性：直接获取 SQLAlchemy Session 实例。"""
        return self._new_session()


# ============================================================================
# DatabaseManager singleton and legacy module-level delegates
# ============================================================================

_db_manager: Optional[DatabaseManager] = None


def get_database_manager() -> DatabaseManager:
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager
