"""
动态存储层：基于 SQL 数据库的动态（朋友圈）持久化存储。
封装对 DynamicPost、DynamicComment、DynamicReadState 表的操作。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple, TYPE_CHECKING

from sqlalchemy import and_, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.utils.logger import get_logger
from src.system.database.sql_database import (
    DynamicPost,
    DynamicComment,
    DynamicReadState,
)
from src.system.database.redis_buffer import RedisBuffer
from src.system.database.sql_writer import run_sql_write

if TYPE_CHECKING:
    from src.system.database.user_store import UserStore

logger = get_logger(__name__)


def _dynamic_is_visible_to_user(dynamic: DynamicPost, user_id: str) -> bool:
    if dynamic.status != "published":
        return False
    return dynamic.visibility == "global" or dynamic.owner_user_id == user_id


class DynamicStore:
    """基于 SQL 数据库的动态存储系统。封装对 DynamicPost、DynamicComment、DynamicReadState 的操作。"""

    def __init__(
        self,
        config: Dict[str, Any],
        sql_session_factory: Callable[[], Session],
        redis_buffer: RedisBuffer,
        user_store: "UserStore",
    ):
        self.config = config
        self.logger = get_logger(__name__)
        self.sql_session_factory = sql_session_factory
        self.user_store = user_store
        _ = redis_buffer  # not used now, but kept for consistency with other stores

    def _get_session(self) -> Session:
        return self.sql_session_factory()

    # ── 静态工具方法 ─────────────────────────────────────────

    @staticmethod
    def _format_timestamp(value: datetime | None) -> Optional[str]:
        if value is None:
            return None
        return value.strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _encode_page_cursor(timestamp: datetime, object_id: str) -> str:
        return f"{timestamp.isoformat()}|{object_id}"

    @staticmethod
    def _decode_page_cursor(cursor: str | None) -> tuple[datetime, str] | None:
        raw = str(cursor or "").strip()
        if not raw or "|" not in raw:
            return None
        timestamp_raw, object_id = raw.split("|", 1)
        try:
            return datetime.fromisoformat(timestamp_raw), object_id
        except ValueError:
            return None

    @staticmethod
    def _author_display_name(author_type: str, author_id: str, user_names: dict[str, str]) -> str:
        if author_type == "user":
            return user_names.get(author_id, "用户")
        if author_type == "agent":
            return "洛天依" if author_id == "luotianyi" else author_id
        if author_type == "system":
            return "系统"
        return author_id or "未知"

    # ── 内部查询工具 ─────────────────────────────────────────

    def _load_user_names(self, db: Session, user_ids: set[str]) -> dict[str, str]:
        return self.user_store.load_user_names_in_session(db, user_ids)

    def _get_or_create_dynamic_read_state(self, db: Session, user_id: str) -> DynamicReadState:
        state = db.query(DynamicReadState).filter(DynamicReadState.user_id == user_id).first()
        if state is not None:
            return state
        state = DynamicReadState(user_id=user_id)
        db.add(state)
        db.flush()
        return state

    def _get_user_preferences(self, db: Session, user_id: str) -> dict[str, Any]:
        return self.user_store.get_user_preferences_in_session(db, user_id)

    def _get_user_description(self, db: Session, user_id: str) -> str:
        return self.user_store.get_user_description_in_session(db, user_id)

    # ── 序列化方法 ───────────────────────────────────────────

    def _serialize_dynamic_post(
        self,
        dynamic: DynamicPost,
        user_names: dict[str, str],
        comment_count: int = 0,
    ) -> dict[str, Any]:
        image_refs: list[Any] = []
        if dynamic.image_refs:
            try:
                image_refs = json.loads(dynamic.image_refs)
            except json.JSONDecodeError:
                image_refs = []
        return {
            "id": dynamic.id,
            "author_type": dynamic.author_type,
            "author_id": dynamic.author_id,
            "author_name": self._author_display_name(dynamic.author_type, dynamic.author_id, user_names),
            "owner_user_id": dynamic.owner_user_id,
            "visibility": dynamic.visibility,
            "content": dynamic.content,
            "image_refs": image_refs,
            "source_type": dynamic.source_type,
            "source_id": dynamic.source_id,
            "allow_comment": bool(dynamic.allow_comment),
            "memory_policy": dynamic.memory_policy,
            "memory_status": dynamic.memory_status,
            "memory_error": dynamic.memory_error,
            "reply_status": dynamic.reply_status,
            "reply_error": dynamic.reply_error,
            "status": dynamic.status,
            "created_at": self._format_timestamp(dynamic.created_at),
            "updated_at": self._format_timestamp(dynamic.updated_at),
            "comment_count": comment_count,
            "cursor": self._encode_page_cursor(dynamic.created_at, dynamic.id),
        }

    def _serialize_dynamic_comment(
        self,
        comment: DynamicComment,
        user_names: dict[str, str],
    ) -> dict[str, Any]:
        return {
            "id": comment.id,
            "dynamic_id": comment.dynamic_id,
            "author_type": comment.author_type,
            "author_id": comment.author_id,
            "author_name": self._author_display_name(comment.author_type, comment.author_id, user_names),
            "owner_user_id": comment.owner_user_id,
            "parent_comment_id": comment.parent_comment_id,
            "content": comment.content,
            "memory_policy": comment.memory_policy,
            "memory_status": comment.memory_status,
            "memory_error": comment.memory_error,
            "reply_status": comment.reply_status,
            "reply_error": comment.reply_error,
            "status": comment.status,
            "created_at": self._format_timestamp(comment.created_at),
            "updated_at": self._format_timestamp(comment.updated_at),
            "cursor": self._encode_page_cursor(comment.created_at, comment.id),
        }

    def _list_thread_comments(self, db: Session, dynamic_id: str) -> list[dict[str, Any]]:
        rows = (
            db.query(DynamicComment)
            .filter(DynamicComment.dynamic_id == dynamic_id)
            .filter(DynamicComment.status == "published")
            .order_by(DynamicComment.created_at.asc(), DynamicComment.id.asc())
            .all()
        )
        user_ids = {row.author_id for row in rows if row.author_type == "user"}
        user_names = self._load_user_names(db, user_ids)
        return [self._serialize_dynamic_comment(row, user_names) for row in rows]

    # ── 动态创建与查询 ───────────────────────────────────────

    def get_dynamic_by_source(
        self,
        *,
        author_type: str,
        author_id: str,
        source_type: str,
        source_id: str,
    ) -> Optional[dict[str, Any]]:
        db = self._get_session()
        try:
            dynamic = (
                db.query(DynamicPost)
                .filter(
                    DynamicPost.author_type == author_type,
                    DynamicPost.author_id == author_id,
                    DynamicPost.source_type == source_type,
                    DynamicPost.source_id == source_id,
                    DynamicPost.status == "published",
                )
                .order_by(DynamicPost.created_at.asc(), DynamicPost.id.asc())
                .first()
            )
            if dynamic is None:
                return None
            user_names = self._load_user_names(
                db,
                {dynamic.author_id} if dynamic.author_type == "user" else set(),
            )
            return self._serialize_dynamic_post(dynamic, user_names=user_names)
        finally:
            db.close()

    def create_dynamic(
        self,
        *,
        author_type: str,
        author_id: str,
        content: str,
        owner_user_id: str | None = None,
        visibility: str = "private",
        source_type: str = "user_post",
        source_id: str | None = None,
        allow_comment: bool = True,
        image_refs: list[Any] | None = None,
        memory_policy: str = "candidate",
        memory_status: str | None = None,
        reply_status: str | None = None,
        idempotent_by_source: bool = False,
    ) -> tuple[bool, str, Optional[dict[str, Any]]]:
        normalized_content = str(content or "").strip()
        if not normalized_content:
            return False, "动态内容不能为空", None
        if visibility not in {"private", "global"}:
            return False, "动态可见性无效", None
        if visibility == "private" and not owner_user_id:
            return False, "私有动态必须绑定所属用户", None

        db = self._get_session()
        try:
            if idempotent_by_source and source_id:
                existing = (
                    db.query(DynamicPost)
                    .filter(
                        DynamicPost.author_type == author_type,
                        DynamicPost.author_id == author_id,
                        DynamicPost.source_type == source_type,
                        DynamicPost.source_id == source_id,
                        DynamicPost.status == "published",
                    )
                    .order_by(DynamicPost.created_at.asc(), DynamicPost.id.asc())
                    .first()
                )
                if existing is not None:
                    user_names = self._load_user_names(
                        db,
                        {existing.author_id} if existing.author_type == "user" else set(),
                    )
                    return (
                        True,
                        "dynamic already exists",
                        self._serialize_dynamic_post(existing, user_names=user_names),
                    )

            image_refs_raw = json.dumps(image_refs or [], ensure_ascii=False) if image_refs is not None else None
            if memory_status is None:
                memory_status = "pending" if memory_policy == "candidate" else "disabled"
            if reply_status is None:
                reply_status = "pending" if author_type == "user" else "not_applicable"

            created: Optional[DynamicPost] = None

            def _write() -> bool:
                nonlocal created
                if owner_user_id:
                    if not self.user_store.user_exists_in_session(db, owner_user_id):
                        return False
                created = DynamicPost(
                    author_type=author_type,
                    author_id=author_id,
                    owner_user_id=owner_user_id,
                    visibility=visibility,
                    content=normalized_content,
                    image_refs=image_refs_raw,
                    source_type=source_type,
                    source_id=source_id,
                    allow_comment=allow_comment,
                    memory_policy=memory_policy,
                    memory_status=memory_status,
                    reply_status=reply_status,
                    status="published",
                )
                db.add(created)
                db.flush()
                if author_type != "user":
                    now = created.created_at or datetime.now()
                    for user_id in self.user_store.list_user_ids_in_session(db):
                        state = self._get_or_create_dynamic_read_state(db, user_id)
                        if state.last_read_dynamic_at is None:
                            continue
                        if state.last_read_dynamic_at > now:
                            state.last_read_dynamic_at = now
                db.commit()
                return True

            success = run_sql_write(_write)
            if not success or created is None:
                return False, "动态创建失败", None
            user_names = self._load_user_names(db, {created.author_id} if created.author_type == "user" else set())
            return True, "ok", self._serialize_dynamic_post(created, user_names=user_names, comment_count=0)
        except IntegrityError as e:
            db.rollback()
            if idempotent_by_source and source_id:
                existing = (
                    db.query(DynamicPost)
                    .filter(
                        DynamicPost.author_type == author_type,
                        DynamicPost.author_id == author_id,
                        DynamicPost.owner_user_id == owner_user_id,
                        DynamicPost.source_type == source_type,
                        DynamicPost.source_id == source_id,
                        DynamicPost.status == "published",
                    )
                    .order_by(DynamicPost.created_at.asc(), DynamicPost.id.asc())
                    .first()
                )
                if existing is not None:
                    user_names = self._load_user_names(
                        db,
                        {existing.author_id} if existing.author_type == "user" else set(),
                    )
                    return (
                        True,
                        "dynamic already exists",
                        self._serialize_dynamic_post(existing, user_names=user_names),
                    )
            self.logger.error(f"Failed to create dynamic due to an integrity constraint: {e}")
            return False, "动态创建失败", None
        except Exception as e:
            self.logger.error(f"Failed to create dynamic: {e}")
            db.rollback()
            return False, "动态创建失败", None
        finally:
            db.close()

    def list_dynamics_for_user(
        self,
        user_id: str,
        *,
        limit: int = 20,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        page_size = min(max(int(limit or 20), 1), 100)
        db = self._get_session()
        try:
            query = (
                db.query(DynamicPost)
                .filter(DynamicPost.status == "published")
                .filter(or_(DynamicPost.visibility == "global", DynamicPost.owner_user_id == user_id))
            )
            decoded_cursor = self._decode_page_cursor(cursor)
            if decoded_cursor is not None:
                cursor_time, cursor_id = decoded_cursor
                query = query.filter(
                    or_(
                        DynamicPost.created_at < cursor_time,
                        and_(DynamicPost.created_at == cursor_time, DynamicPost.id < cursor_id),
                    )
                )
            rows = (
                query.order_by(DynamicPost.created_at.desc(), DynamicPost.id.desc())
                .limit(page_size + 1)
                .all()
            )
            has_more = len(rows) > page_size
            page_rows = rows[:page_size]
            user_names = self._load_user_names(
                db,
                {row.author_id for row in page_rows if row.author_type == "user"},
            )
            dynamic_ids = [row.id for row in page_rows]
            comment_counts: dict[str, int] = {}
            if dynamic_ids:
                counts = (
                    db.query(DynamicComment.dynamic_id, func.count(DynamicComment.id))
                    .filter(DynamicComment.dynamic_id.in_(dynamic_ids))
                    .filter(DynamicComment.status == "published")
                    .filter(DynamicComment.owner_user_id == user_id)
                    .group_by(DynamicComment.dynamic_id)
                    .all()
                )
                comment_counts = {dynamic_id: count for dynamic_id, count in counts}
            items = [
                self._serialize_dynamic_post(row, user_names, comment_counts.get(row.id, 0))
                for row in page_rows
            ]
            next_cursor = items[-1]["cursor"] if has_more and items else None
            return {"items": items, "has_more": has_more, "next_cursor": next_cursor}
        finally:
            db.close()

    def get_dynamic_by_id_for_user(self, user_id: str, dynamic_id: str) -> Optional[DynamicPost]:
        db = self._get_session()
        try:
            dynamic = db.query(DynamicPost).filter(DynamicPost.id == dynamic_id).first()
            if dynamic is None or not _dynamic_is_visible_to_user(dynamic, user_id):
                return None
            db.expunge(dynamic)
            return dynamic
        finally:
            db.close()

    # ── 评论创建与查询 ───────────────────────────────────────

    def list_dynamic_comments_for_user(
        self,
        user_id: str,
        dynamic_id: str,
        *,
        limit: int = 100,
        cursor: str | None = None,
    ) -> tuple[bool, str, dict[str, Any]]:
        page_size = min(max(int(limit or 100), 1), 200)
        db = self._get_session()
        try:
            dynamic = db.query(DynamicPost).filter(DynamicPost.id == dynamic_id).first()
            if dynamic is None or not _dynamic_is_visible_to_user(dynamic, user_id):
                return False, "动态不存在或无权访问", {"items": [], "has_more": False, "next_cursor": None}

            query = (
                db.query(DynamicComment)
                .filter(DynamicComment.dynamic_id == dynamic_id)
                .filter(DynamicComment.owner_user_id == user_id)
                .filter(DynamicComment.status == "published")
            )
            decoded_cursor = self._decode_page_cursor(cursor)
            if decoded_cursor is not None:
                cursor_time, cursor_id = decoded_cursor
                query = query.filter(
                    or_(
                        DynamicComment.created_at > cursor_time,
                        and_(DynamicComment.created_at == cursor_time, DynamicComment.id > cursor_id),
                    )
                )
            rows = (
                query.order_by(DynamicComment.created_at.asc(), DynamicComment.id.asc())
                .limit(page_size + 1)
                .all()
            )
            has_more = len(rows) > page_size
            page_rows = rows[:page_size]
            user_names = self._load_user_names(
                db,
                {row.author_id for row in page_rows if row.author_type == "user"},
            )
            items = [self._serialize_dynamic_comment(row, user_names) for row in page_rows]
            next_cursor = items[-1]["cursor"] if has_more and items else None
            return True, "ok", {"items": items, "has_more": has_more, "next_cursor": next_cursor}
        finally:
            db.close()

    def create_dynamic_comment(
        self,
        *,
        dynamic_id: str,
        author_type: str,
        author_id: str,
        owner_user_id: str,
        content: str,
        parent_comment_id: str | None = None,
        memory_policy: str = "candidate",
        memory_status: str | None = None,
        reply_status: str | None = None,
    ) -> tuple[bool, str, Optional[dict[str, Any]]]:
        normalized_content = str(content or "").strip()
        if not normalized_content:
            return False, "评论内容不能为空", None

        db = self._get_session()
        try:
            if memory_status is None:
                memory_status = "pending" if memory_policy == "candidate" else "disabled"
            if reply_status is None:
                reply_status = "pending" if author_type == "user" else "not_applicable"
            created: Optional[DynamicComment] = None

            def _write() -> bool:
                nonlocal created
                dynamic = db.query(DynamicPost).filter(DynamicPost.id == dynamic_id).first()
                if dynamic is None or dynamic.status != "published":
                    return False
                if author_type == "user" and not _dynamic_is_visible_to_user(dynamic, owner_user_id):
                    return False
                if not dynamic.allow_comment:
                    return False
                if dynamic.visibility == "private" and dynamic.owner_user_id != owner_user_id:
                    return False
                if parent_comment_id:
                    parent = db.query(DynamicComment).filter(DynamicComment.id == parent_comment_id).first()
                    if parent is None or parent.dynamic_id != dynamic_id or parent.owner_user_id != owner_user_id:
                        return False
                if not self.user_store.user_exists_in_session(db, owner_user_id):
                    return False
                created = DynamicComment(
                    dynamic_id=dynamic_id,
                    author_type=author_type,
                    author_id=author_id,
                    owner_user_id=owner_user_id,
                    parent_comment_id=parent_comment_id,
                    content=normalized_content,
                    memory_policy=memory_policy,
                    memory_status=memory_status,
                    reply_status=reply_status,
                    status="published",
                )
                db.add(created)
                db.flush()
                db.commit()
                return True

            success = run_sql_write(_write)
            if not success or created is None:
                return False, "评论创建失败", None
            user_names = self._load_user_names(db, {created.author_id} if created.author_type == "user" else set())
            return True, "ok", self._serialize_dynamic_comment(created, user_names)
        except Exception as e:
            self.logger.error(f"Failed to create dynamic comment: {e}")
            db.rollback()
            return False, "评论创建失败", None
        finally:
            db.close()

    # ── 未读状态 ─────────────────────────────────────────────

    def get_dynamic_unread_status(self, user_id: str) -> dict[str, Any]:
        db = self._get_session()
        try:
            state = self._get_or_create_dynamic_read_state(db, user_id)
            db.commit()
            unread_dynamic_count = (
                db.query(func.count(DynamicPost.id))
                .filter(DynamicPost.status == "published")
                .filter(DynamicPost.author_type != "user")
                .filter(or_(DynamicPost.visibility == "global", DynamicPost.owner_user_id == user_id))
                .filter(
                    DynamicPost.created_at > state.last_read_dynamic_at
                    if state.last_read_dynamic_at is not None
                    else True
                )
                .scalar()
                or 0
            )
            unread_comment_count = (
                db.query(func.count(DynamicComment.id))
                .filter(DynamicComment.status == "published")
                .filter(DynamicComment.owner_user_id == user_id)
                .filter(DynamicComment.author_type != "user")
                .filter(
                    DynamicComment.created_at > state.last_read_comment_at
                    if state.last_read_comment_at is not None
                    else True
                )
                .scalar()
                or 0
            )
            total = unread_dynamic_count + unread_comment_count
            return {
                "has_unread": total > 0,
                "unread_count": total,
                "unread_dynamic_count": unread_dynamic_count,
                "unread_comment_count": unread_comment_count,
                "last_read_dynamic_at": self._format_timestamp(state.last_read_dynamic_at),
                "last_read_comment_at": self._format_timestamp(state.last_read_comment_at),
            }
        finally:
            db.close()

    def mark_dynamic_read(self, user_id: str) -> dict[str, Any]:
        db = self._get_session()
        try:
            now = datetime.now()

            def _write() -> DynamicReadState:
                state = self._get_or_create_dynamic_read_state(db, user_id)
                state.last_read_dynamic_at = now
                state.last_read_comment_at = now
                db.commit()
                return state

            state = run_sql_write(_write)
            return {
                "ok": True,
                "last_read_dynamic_at": self._format_timestamp(state.last_read_dynamic_at),
                "last_read_comment_at": self._format_timestamp(state.last_read_comment_at),
            }
        except Exception as e:
            self.logger.error(f"Failed to mark dynamic read for user {user_id}: {e}")
            db.rollback()
            return {"ok": False}
        finally:
            db.close()

    # ── 待回复队列 ───────────────────────────────────────────

    def list_pending_dynamic_posts_for_reply(self, *, limit: int = 20) -> list[dict[str, Any]]:
        page_size = min(max(int(limit or 20), 1), 200)
        db = self._get_session()
        try:
            rows = (
                db.query(DynamicPost)
                .filter(DynamicPost.author_type == "user")
                .filter(DynamicPost.status == "published")
                .filter(DynamicPost.reply_status == "pending")
                .order_by(DynamicPost.created_at.asc(), DynamicPost.id.asc())
                .limit(page_size)
                .all()
            )
            user_names = self._load_user_names(db, {row.author_id for row in rows})
            items = []
            for row in rows:
                item = self._serialize_dynamic_post(row, user_names, 0)
                uid = row.owner_user_id or row.author_id
                item["username"] = user_names.get(row.author_id, "")
                item["user_description"] = self._get_user_description(db, uid) or ""
                item["preferences"] = self._get_user_preferences(db, uid)
                item["thread_comments"] = self._list_thread_comments(db, row.id)
                items.append(item)
            return items
        finally:
            db.close()

    def list_pending_dynamic_comments_for_reply(self, *, limit: int = 20) -> list[dict[str, Any]]:
        page_size = min(max(int(limit or 20), 1), 200)
        db = self._get_session()
        try:
            rows = (
                db.query(DynamicComment, DynamicPost)
                .join(DynamicPost, DynamicComment.dynamic_id == DynamicPost.id)
                .filter(DynamicComment.author_type == "user")
                .filter(DynamicComment.status == "published")
                .filter(DynamicComment.reply_status == "pending")
                .order_by(DynamicComment.created_at.asc(), DynamicComment.id.asc())
                .limit(page_size)
                .all()
            )
            user_ids = {comment.author_id for comment, _ in rows if comment.author_type == "user"}
            user_names = self._load_user_names(db, user_ids)
            items = []
            for comment, dynamic in rows:
                item = self._serialize_dynamic_comment(comment, user_names)
                item["dynamic"] = self._serialize_dynamic_post(dynamic, user_names, 0)
                item["username"] = user_names.get(comment.author_id, "")
                item["user_description"] = self._get_user_description(db, comment.owner_user_id) or ""
                item["preferences"] = self._get_user_preferences(db, comment.owner_user_id)
                item["thread_comments"] = self._list_thread_comments(db, dynamic.id)
                items.append(item)
            return items
        finally:
            db.close()

    def update_dynamic_post_reply_state(
        self,
        dynamic_id: str,
        *,
        status: str,
        error: str | None = None,
    ) -> bool:
        db = self._get_session()
        try:
            def _write() -> bool:
                row = db.query(DynamicPost).filter(DynamicPost.id == dynamic_id).first()
                if row is None:
                    return False
                row.reply_status = status
                row.reply_error = error
                db.commit()
                return True

            return bool(run_sql_write(_write))
        except Exception as e:
            self.logger.error(f"Failed to update dynamic post reply state for {dynamic_id}: {e}")
            db.rollback()
            return False
        finally:
            db.close()

    def update_dynamic_comment_reply_state(
        self,
        comment_id: str,
        *,
        status: str,
        error: str | None = None,
    ) -> bool:
        db = self._get_session()
        try:
            def _write() -> bool:
                row = db.query(DynamicComment).filter(DynamicComment.id == comment_id).first()
                if row is None:
                    return False
                row.reply_status = status
                row.reply_error = error
                db.commit()
                return True

            return bool(run_sql_write(_write))
        except Exception as e:
            self.logger.error(f"Failed to update dynamic comment reply state for {comment_id}: {e}")
            db.rollback()
            return False
        finally:
            db.close()

    # ── 待记忆队列 ───────────────────────────────────────────

    def list_pending_dynamic_posts_for_memory(self, *, limit: int = 20) -> list[dict[str, Any]]:
        page_size = min(max(int(limit or 20), 1), 200)
        db = self._get_session()
        try:
            rows = (
                db.query(DynamicPost)
                .filter(DynamicPost.author_type == "user")
                .filter(DynamicPost.status == "published")
                .filter(DynamicPost.memory_policy == "candidate")
                .filter(DynamicPost.memory_status == "pending")
                .order_by(DynamicPost.created_at.asc(), DynamicPost.id.asc())
                .limit(page_size)
                .all()
            )
            user_names = self._load_user_names(db, {row.author_id for row in rows})
            items = []
            for row in rows:
                item = self._serialize_dynamic_post(row, user_names, 0)
                item["username"] = user_names.get(row.author_id, "")
                items.append(item)
            return items
        finally:
            db.close()

    def list_pending_dynamic_comments_for_memory(self, *, limit: int = 20) -> list[dict[str, Any]]:
        page_size = min(max(int(limit or 20), 1), 200)
        db = self._get_session()
        try:
            rows = (
                db.query(DynamicComment, DynamicPost)
                .join(DynamicPost, DynamicComment.dynamic_id == DynamicPost.id)
                .filter(DynamicComment.author_type == "user")
                .filter(DynamicComment.status == "published")
                .filter(DynamicComment.memory_policy == "candidate")
                .filter(DynamicComment.memory_status == "pending")
                .order_by(DynamicComment.created_at.asc(), DynamicComment.id.asc())
                .limit(page_size)
                .all()
            )
            user_names = self._load_user_names(db, {comment.author_id for comment, _ in rows})
            items = []
            for comment, dynamic in rows:
                item = self._serialize_dynamic_comment(comment, user_names)
                item["dynamic"] = self._serialize_dynamic_post(dynamic, user_names, 0)
                item["username"] = user_names.get(comment.author_id, "")
                items.append(item)
            return items
        finally:
            db.close()

    def update_dynamic_post_memory_state(
        self,
        dynamic_id: str,
        *,
        status: str,
        error: str | None = None,
    ) -> bool:
        db = self._get_session()
        try:
            def _write() -> bool:
                row = db.query(DynamicPost).filter(DynamicPost.id == dynamic_id).first()
                if row is None:
                    return False
                row.memory_status = status
                row.memory_error = error
                db.commit()
                return True

            return bool(run_sql_write(_write))
        except Exception as e:
            self.logger.error(f"Failed to update dynamic post memory state for {dynamic_id}: {e}")
            db.rollback()
            return False
        finally:
            db.close()

    def update_dynamic_comment_memory_state(
        self,
        comment_id: str,
        *,
        status: str,
        error: str | None = None,
    ) -> bool:
        db = self._get_session()
        try:
            def _write() -> bool:
                row = db.query(DynamicComment).filter(DynamicComment.id == comment_id).first()
                if row is None:
                    return False
                row.memory_status = status
                row.memory_error = error
                db.commit()
                return True

            return bool(run_sql_write(_write))
        except Exception as e:
            self.logger.error(f"Failed to update dynamic comment memory state for {comment_id}: {e}")
            db.rollback()
            return False
        finally:
            db.close()

    # ── 管理接口 ─────────────────────────────────────────────

    def admin_list_dynamics(
        self,
        *,
        limit: int = 100,
        cursor: str | None = None,
        owner_user_id: str | None = None,
        author_type: str | None = None,
        source_type: str | None = None,
        status: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> dict[str, Any]:
        page_size = min(max(int(limit or 100), 1), 500)
        db = self._get_session()
        try:
            query = db.query(DynamicPost)
            if owner_user_id:
                query = query.filter(DynamicPost.owner_user_id == owner_user_id)
            if author_type:
                query = query.filter(DynamicPost.author_type == author_type)
            if source_type:
                query = query.filter(DynamicPost.source_type == source_type)
            if status:
                query = query.filter(DynamicPost.status == status)
            if created_after:
                query = query.filter(DynamicPost.created_at >= created_after)
            if created_before:
                query = query.filter(DynamicPost.created_at <= created_before)
            decoded_cursor = self._decode_page_cursor(cursor)
            if decoded_cursor is not None:
                cursor_time, cursor_id = decoded_cursor
                query = query.filter(
                    or_(
                        DynamicPost.created_at < cursor_time,
                        and_(DynamicPost.created_at == cursor_time, DynamicPost.id < cursor_id),
                    )
                )
            rows = query.order_by(DynamicPost.created_at.desc(), DynamicPost.id.desc()).limit(page_size + 1).all()
            has_more = len(rows) > page_size
            page_rows = rows[:page_size]
            user_names = self._load_user_names(db, {row.author_id for row in page_rows if row.author_type == "user"})
            dynamic_ids = [row.id for row in page_rows]
            comment_counts: dict[str, int] = {}
            if dynamic_ids:
                counts = (
                    db.query(DynamicComment.dynamic_id, func.count(DynamicComment.id))
                    .filter(DynamicComment.dynamic_id.in_(dynamic_ids))
                    .filter(DynamicComment.status == "published")
                    .group_by(DynamicComment.dynamic_id)
                    .all()
                )
                comment_counts = {dynamic_id: count for dynamic_id, count in counts}
            items = [
                self._serialize_dynamic_post(row, user_names, comment_counts.get(row.id, 0))
                for row in page_rows
            ]
            next_cursor = items[-1]["cursor"] if has_more and items else None
            return {"items": items, "has_more": has_more, "next_cursor": next_cursor}
        finally:
            db.close()

    def admin_list_dynamic_comments(
        self,
        dynamic_id: str,
        *,
        limit: int = 200,
        owner_user_id: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> dict[str, Any]:
        page_size = min(max(int(limit or 200), 1), 500)
        db = self._get_session()
        try:
            query = db.query(DynamicComment).filter(DynamicComment.dynamic_id == dynamic_id)
            if owner_user_id:
                query = query.filter(DynamicComment.owner_user_id == owner_user_id)
            if created_after:
                query = query.filter(DynamicComment.created_at >= created_after)
            if created_before:
                query = query.filter(DynamicComment.created_at <= created_before)
            rows = query.order_by(DynamicComment.created_at.asc(), DynamicComment.id.asc()).limit(page_size).all()
            user_names = self._load_user_names(db, {row.author_id for row in rows if row.author_type == "user"})
            items = [self._serialize_dynamic_comment(row, user_names) for row in rows]
            return {"items": items}
        finally:
            db.close()
