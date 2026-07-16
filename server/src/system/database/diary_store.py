"""
日记存储层：基于 SQL 数据库的日记持久化存储。
封装对 DiaryEntry 表的操作，供 DiaryCapability 和 WorldTask 调用。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, date
from typing import Any, Callable, Dict, List, Optional, Tuple, TYPE_CHECKING

from sqlalchemy import and_, desc
from sqlalchemy.orm import Session

from src.utils.logger import get_logger
from src.system.database.sql_database import DiaryEntry

if TYPE_CHECKING:
    from src.system.database.redis_buffer import RedisBuffer

logger = get_logger(__name__)


class DiaryStore:
    """基于 SQL 数据库的日记存储系统。封装对 DiaryEntry 表的操作。"""

    def __init__(
        self,
        config: Dict[str, Any],
        sql_session_factory: Callable[[], Session],
        redis_buffer: RedisBuffer,
    ):
        self.config = config
        self.logger = get_logger(__name__)
        self.sql_session_factory = sql_session_factory
        self.redis_buffer = redis_buffer

    def _get_session(self) -> Session:
        return self.sql_session_factory()

    # ── 查询 ─────────────────────────────────────────────

    def get_diary(self, diary_id: str) -> Optional[Dict[str, Any]]:
        """根据 ID 获取单篇日记。"""
        db = self._get_session()
        try:
            entry = db.query(DiaryEntry).filter(DiaryEntry.id == diary_id).first()
            if entry is None:
                return None
            return self._entry_to_dict(entry)
        finally:
            db.close()

    def list_diaries(
        self,
        user_id: str,
        *,
        character_id: str = "luotianyi",
        limit: int = 20,
        cursor: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        """列出用户可见的日记，按日期倒序排列。"""
        db = self._get_session()
        try:
            query = db.query(DiaryEntry).filter(
                DiaryEntry.user_id == user_id,
                DiaryEntry.character_id == character_id,
                DiaryEntry.status == "published",
            )

            if cursor:
                query = query.filter(DiaryEntry.diary_date < cursor)

            if date_from:
                query = query.filter(DiaryEntry.diary_date >= date_from)

            if date_to:
                query = query.filter(DiaryEntry.diary_date <= date_to)

            entries = (
                query.order_by(desc(DiaryEntry.diary_date))
                .limit(limit + 1)
                .all()
            )

            has_more = len(entries) > limit
            items = [self._entry_to_dict(e) for e in entries[:limit]]
            next_cursor = items[-1]["diary_date"] if items and has_more else None

            return {
                "ok": True,
                "items": items,
                "has_more": has_more,
                "next_cursor": next_cursor,
            }
        finally:
            db.close()

    def get_diary_by_date(
        self,
        user_id: str,
        diary_date: str,
        *,
        character_id: str = "luotianyi",
    ) -> Optional[Dict[str, Any]]:
        """根据日期获取某篇日记。"""
        db = self._get_session()
        try:
            entry = (
                db.query(DiaryEntry)
                .filter(
                    DiaryEntry.user_id == user_id,
                    DiaryEntry.character_id == character_id,
                    DiaryEntry.diary_date == diary_date,
                )
                .first()
            )
            if entry is None:
                return None
            return self._entry_to_dict(entry)
        finally:
            db.close()

    def has_diary_for_date(
        self,
        user_id: str,
        diary_date: str,
        *,
        character_id: str = "luotianyi",
    ) -> bool:
        """检查某天是否已有日记。"""
        db = self._get_session()
        try:
            count = (
                db.query(DiaryEntry)
                .filter(
                    DiaryEntry.user_id == user_id,
                    DiaryEntry.character_id == character_id,
                    DiaryEntry.diary_date == diary_date,
                )
                .count()
            )
            return count > 0
        finally:
            db.close()

    def list_available_dates(
        self,
        user_id: str,
        *,
        character_id: str = "luotianyi",
        limit: int = 30,
    ) -> List[str]:
        """列出用户有日记的日期（用于日历展示）。"""
        db = self._get_session()
        try:
            results = (
                db.query(DiaryEntry.diary_date)
                .filter(
                    DiaryEntry.user_id == user_id,
                    DiaryEntry.character_id == character_id,
                    DiaryEntry.status == "published",
                )
                .order_by(desc(DiaryEntry.diary_date))
                .limit(limit)
                .all()
            )
            return [r[0] for r in results]
        finally:
            db.close()

    # ── 写入 ─────────────────────────────────────────────

    def create_diary(
        self,
        user_id: str,
        diary_date: str,
        *,
        character_id: str = "luotianyi",
        title: str,
        content: str,
        summary: Optional[str] = None,
        mood: Optional[str] = None,
        tags: Optional[List[str]] = None,
        source: str = "auto",
        metadata_json: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """创建一篇日记。如果当天已有日记则返回 (False, '已存在', None)。"""
        if self.has_diary_for_date(user_id, diary_date, character_id=character_id):
            return False, "该日期已有日记", None

        db = self._get_session()
        try:
            entry = DiaryEntry(
                id=str(uuid.uuid4()),
                user_id=user_id,
                character_id=character_id,
                diary_date=diary_date,
                title=title,
                content=content,
                summary=summary,
                mood=mood,
                tags=json.dumps(tags, ensure_ascii=False) if tags else None,
                source=source,
                status="published",
                metadata_json=metadata_json,
            )
            db.add(entry)
            db.commit()
            db.refresh(entry)
            return True, "创建成功", self._entry_to_dict(entry)
        except Exception as e:
            db.rollback()
            logger.error(f"创建日记失败: {e}")
            return False, f"创建失败: {str(e)}", None
        finally:
            db.close()

    def delete_diary(self, diary_id: str, user_id: str) -> bool:
        """删除一篇日记。"""
        db = self._get_session()
        try:
            entry = (
                db.query(DiaryEntry)
                .filter(DiaryEntry.id == diary_id, DiaryEntry.user_id == user_id)
                .first()
            )
            if entry is None:
                return False
            entry.status = "deleted"
            db.commit()
            return True
        except Exception as e:
            db.rollback()
            logger.error(f"删除日记失败: {e}")
            return False
        finally:
            db.close()

    # ── 统计 ─────────────────────────────────────────────

    def count_diaries(self, user_id: str, *, character_id: str = "luotianyi") -> int:
        """统计用户日记总数。"""
        db = self._get_session()
        try:
            return (
                db.query(DiaryEntry)
                .filter(
                    DiaryEntry.user_id == user_id,
                    DiaryEntry.character_id == character_id,
                    DiaryEntry.status == "published",
                )
                .count()
            )
        finally:
            db.close()

    # ── 内部工具 ─────────────────────────────────────────

    @staticmethod
    def _entry_to_dict(entry: DiaryEntry) -> Dict[str, Any]:
        return {
            "id": entry.id,
            "user_id": entry.user_id,
            "character_id": entry.character_id,
            "diary_date": entry.diary_date,
            "title": entry.title,
            "content": entry.content,
            "summary": entry.summary,
            "mood": entry.mood,
            "tags": json.loads(entry.tags) if entry.tags else None,
            "source": entry.source,
            "status": entry.status,
            "created_at": entry.created_at.strftime("%Y-%m-%d %H:%M:%S") if entry.created_at else None,
            "updated_at": entry.updated_at.strftime("%Y-%m-%d %H:%M:%S") if entry.updated_at else None,
        }