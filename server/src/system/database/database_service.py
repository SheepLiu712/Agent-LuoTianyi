import os
from typing import Any, Dict, Optional, TYPE_CHECKING

from src.system.database.services.conversation_service import ConversationService
from src.system.database.services.credential_service import CredentialService, JWT_SECRET_ENV
from src.system.database.services.dynamic_store import DynamicStore
from src.system.database.services.event_store import EventStore
from src.system.database.services.memory_store import MemoryStore
from src.system.database.redis_buffer import RedisBuffer, get_redis_buffer, init_redis_buffer
from src.system.database.sql_database import SessionLocal, get_sql_session, init_sql_db
from src.system.database.services.user_store import UserStore
from src.system.database.utils import (
    DEFAULT_MESSAGE_TOKEN_TTL_SECONDS,
    normalize_message_token_ttl_seconds,
)
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from src.utils.llm_service import LLMService


logger = get_logger("database")


class DatabaseManager:
    """
    数据库组件组合根，负责初始化基础设施和各数据库服务。

    - 内部持有 RedisBuffer (redis) 实例
    - 数据库服务方法自行创建 SessionLocal() 并通过 try/finally 确保关闭
    - 不再要求调用者传入 db 和 redis 参数
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self.jwt_secret = os.environ.get(JWT_SECRET_ENV)
        self.message_token_ttl_seconds = normalize_message_token_ttl_seconds(
            self.config.get(
                "message_token_ttl_seconds",
                DEFAULT_MESSAGE_TOKEN_TTL_SECONDS,
            )
        )
        self._redis: Optional[RedisBuffer] = None
        self.event_store: Optional[EventStore] = None
        self.memory_store: Optional[MemoryStore] = None
        self.dynamic_store: Optional[DynamicStore] = None
        self.user_store: Optional[UserStore] = None
        self.credential_service: Optional[CredentialService] = None
        self.conversation_service: Optional[ConversationService] = None
        self.init_all_databases()

    def init_all_databases(self) -> None:
        """初始化所有数据库组件（SQL/Redis 缓存）。"""
        try:
            init_sql_db(
                self.config.get("sql_db_folder", "data/database"),
                self.config.get("sql_db_file", "luotianyi.db"),
            )
            init_redis_buffer(self.config.get("redis", {}))

            self.user_store = UserStore(
                config=self.config.get("user_store", {}),
                sql_session_factory=self.open_sql_session,
                redis_buffer=self._ensure_redis(),
            )
            self.event_store = EventStore(
                config=self.config.get("event_store", {}),
                sql_session_factory=self.open_sql_session,
                redis_buffer=self._ensure_redis(),
            )
            self.memory_store = MemoryStore(
                config=self.config.get("memory_store", {}),
                sql_session_factory=self.open_sql_session,
                redis_buffer=self._ensure_redis(),
            )
            self.dynamic_store = DynamicStore(
                config=self.config.get("dynamic_store", {}),
                sql_session_factory=self.open_sql_session,
                redis_buffer=self._ensure_redis(),
                user_store=self.user_store,
            )
            self.credential_service = CredentialService(
                sql_session_factory=self.open_sql_session,
                redis_buffer=self._ensure_redis(),
                jwt_secret=self.jwt_secret,
                message_token_ttl_seconds=self.message_token_ttl_seconds,
            )
            self.conversation_service = ConversationService(
                sql_session_factory=self.open_sql_session,
                redis_buffer=self._ensure_redis(),
                user_store=self.user_store,
            )
            logger.info("Main database initialized successfully.")
        except Exception as e:
            logger.error(f"Error initializing databases: {e}")
            raise

    def create_llm_modules(self, llm_service: "LLMService") -> None:
        if self.event_store is not None:
            self.event_store.create_llm_module(llm_service)
        if self.memory_store is not None:
            self.memory_store.create_llm_module(llm_service)

    def wire_dependencies(self, *, llm_service: "LLMService") -> None:
        """向数据库子模块派发外部依赖。"""
        self.create_llm_modules(llm_service)
        self.ensure_dependencies()

    def ensure_dependencies(self) -> None:
        """检查数据库管理器和子存储已经初始化。"""
        required = {
            "redis": self._ensure_redis(),
            "user_store": self.user_store,
            "event_store": self.event_store,
            "memory_store": self.memory_store,
            "dynamic_store": self.dynamic_store,
            "credential_service": self.credential_service,
            "conversation_service": self.conversation_service,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise RuntimeError(f"DatabaseManager dependencies are missing: {', '.join(missing)}")

    async def shutdown(self) -> None:
        """关闭数据库后台资源；当前内存 Redis 实现无需额外释放。"""
        return None

    # ── 内部工具 ─────────────────────────────────────────────

    def _ensure_redis(self) -> RedisBuffer:
        if self._redis is None:
            # 自动从 get_redis_buffer 获取已初始化的实例
            self._redis = get_redis_buffer()
        return self._redis


    def _new_session(self) -> "Session":
        """创建一个新的 SQL 会话。调用者负责关闭。"""
        try:
            return get_sql_session()
        except Exception:
            # fallback: 如果 sql db 还未初始化，尝试直接使用 SessionLocal
            if SessionLocal is not None:
                return SessionLocal()
            raise

    def open_sql_session(self) -> "Session":
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

    # ── 公共基础设施方法 ──────────────────────────────────────

    @property
    def redis(self) -> RedisBuffer:
        """便捷属性：直接访问 Redis 实例。"""
        return self._ensure_redis()
    
    def get_sql_session(self) -> "Session":
        """便捷属性：直接获取 SQLAlchemy Session 实例。"""
        return self._new_session()


# ============================================================================
# DatabaseManager singleton
# ============================================================================

_db_manager: Optional[DatabaseManager] = None


def get_database_manager() -> DatabaseManager:
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager

def set_default_database_manager(manager: DatabaseManager) -> None:
    global _db_manager
    _db_manager = manager
