from __future__ import annotations

import json
from typing import Any, Callable, Dict, Optional

from sqlalchemy.orm import Session

from src.system.database.redis_buffer import RedisBuffer
from src.system.database.sql_database import User
from src.system.database.sql_writer import run_sql_write
from src.utils.logger import get_logger


logger = get_logger(__name__)


class UserStore:
    """用户表读写与用户相关缓存。

    DatabaseManager 通过组合后的服务把用户相关能力暴露给上层；其它子存储如果需要
    用户画像、偏好或用户名，也通过 UserStore 读取，避免反向调用 DatabaseManager。
    """

    def __init__(
        self,
        config: Dict[str, Any],
        sql_session_factory: Callable[[], Session],
        redis_buffer: RedisBuffer,
    ) -> None:
        self.config = config or {}
        self.sql_session_factory = sql_session_factory
        self.redis = redis_buffer

    def _get_session(self) -> Session:
        return self.sql_session_factory()

    @staticmethod
    def normalize_preferences(value: Any) -> Dict[str, Any]:
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

    def load_user_names(self, user_ids: set[str]) -> dict[str, str]:
        if not user_ids:
            return {}
        db = self._get_session()
        try:
            rows = db.query(User.uuid, User.username).filter(User.uuid.in_(user_ids)).all()
            return {row[0]: row[1] for row in rows}
        finally:
            db.close()

    def load_user_names_in_session(self, db: Session, user_ids: set[str]) -> dict[str, str]:
        if not user_ids:
            return {}
        rows = db.query(User.uuid, User.username).filter(User.uuid.in_(user_ids)).all()
        return {row[0]: row[1] for row in rows}

    def user_exists_in_session(self, db: Session, user_id: str) -> bool:
        if not user_id:
            return False
        return db.query(User.uuid).filter(User.uuid == user_id).first() is not None

    def list_user_ids_in_session(self, db: Session) -> list[str]:
        rows = db.query(User.uuid).all()
        return [row[0] for row in rows]

    def get_user_preferences(self, user_id: str) -> Optional[Dict[str, Any]]:
        cached_preferences = self.redis.get(f"user_preferences:{user_id}")
        if cached_preferences:
            return self.normalize_preferences(cached_preferences)

        db = self._get_session()
        try:
            user = db.query(User).filter_by(uuid=user_id).first()
            if not user:
                return None
            preferences = self.normalize_preferences(user.preferences)
            self.redis.setex(f"user_preferences:{user_id}", 3600, preferences)
            return preferences
        finally:
            db.close()

    def get_user_preferences_in_session(self, db: Session, user_id: str) -> dict[str, Any]:
        user = db.query(User).filter(User.uuid == user_id).first()
        if user is None:
            return {}
        return self.normalize_preferences(user.preferences)

    def save_user_preferences(self, user_id: str, preferences: Dict[str, Any]) -> bool:
        db = self._get_session()
        try:
            user = db.query(User).filter_by(uuid=user_id).first()
            if not user:
                return False
            user.preferences = json.dumps(preferences, ensure_ascii=False)
            db.commit()
            self.redis.setex(f"user_preferences:{user_id}", 3600, preferences)
            return True
        except Exception as e:
            logger.error(f"Failed to save preferences for user {user_id}: {e}")
            db.rollback()
            return False
        finally:
            db.close()

    def update_user_description(self, user_id: str, new_description: str, commit: bool = True) -> None:
        db = self._get_session()
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
                self.redis.setex(f"user_description:{user_id}", 3600, new_description)
        except Exception as e:
            logger.error(f"update_user_description error: {e}")
            db.rollback()
        finally:
            db.close()

    def get_user_description(self, user_id: str) -> Optional[str]:
        redis_key = f"user_description:{user_id}"
        description = self.redis.get(redis_key)
        if description is not None:
            return description

        db = self._get_session()
        try:
            user = db.query(User).filter(User.uuid == user_id).first()
            if not user:
                return None
            description = user.description or ""
            self.redis.setex(redis_key, 3600, description)
            return description
        finally:
            db.close()

    def get_user_description_in_session(self, db: Session, user_id: str) -> str:
        user = db.query(User).filter(User.uuid == user_id).first()
        if user is None:
            return ""
        return user.description or ""
