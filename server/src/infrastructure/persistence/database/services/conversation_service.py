import json
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from src.domain import ConversationItem
from src.domain.conversation_type import ContextInfo
from src.infrastructure.persistence.cognitive_maintenance import (
    ORIGIN_PROGRESS_KEY,
    CognitiveMaintenanceBatch,
    CognitiveMaintenanceBatchDraft,
)
from src.infrastructure.persistence.database.redis_buffer import RedisBuffer, WatchError
from src.infrastructure.persistence.database.sql_database import (
    CognitiveMaintenanceBatch as CognitiveMaintenanceBatchRecord,
)
from src.infrastructure.persistence.database.sql_database import (
    Conversation,
    ConversationContext,
    User,
)
from src.infrastructure.persistence.database.sql_writer import run_sql_write
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from src.infrastructure.persistence.database.services.user_store import UserStore


logger = get_logger("database.conversation")


class ConversationIdentityConflict(RuntimeError):
    """A conversation UUID was reused for a different logical message."""


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
        """
        兼容性地获取或创建 ConversationContext 对象。若不存在，则创建一个新的 ConversationContext 并返回。
        """
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
        """
        获取用户的聊天偏好设置。返回字典，如果用户不存在则返回 None。
        """
        if self.user_store is None:
            return None
        return self.user_store.get_user_preferences(user_id)

    def save_user_preferences(self, user_id: str, preferences: Dict[str, Any]) -> bool:
        """
        更新数据库中的用户聊天偏好设置，并同步更新 Redis 缓存。成功返回 True，失败返回 False。
        """
        if self.user_store is None:
            return False
        return self.user_store.save_user_preferences(user_id, preferences)

    def update_user_description(self, user_id: str, new_description: str, commit: bool = True) -> bool:
        """更新 user_id 的画像；commit 控制提交，返回是否写入成功。"""
        if self.user_store is None:
            return False
        return self.user_store.update_user_description(user_id, new_description, commit=commit)

    def get_user_description(self, user_id: str) -> Optional[str]:
        """获取用户画像描述。"""
        if self.user_store is None:
            return None
        return self.user_store.get_user_description(user_id)

    def get_user_nickname(self, user_id: str) -> Optional[str]:
        """获取用户昵称。"""
        raise NotImplementedError(
            "get_user_nickname is deprecated. Use get_user_description or get_user_preferences instead."
        )
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
        """
        不该使用
        """
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
        raise NotImplementedError(
            "update_user_nickname is deprecated. Use update_user_description or update_user_preferences instead."
        )
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
                    .order_by(Conversation.timestamp.desc(), Conversation.uuid.desc())
                    .limit(context_memory_count)
                    .all()
                )
                context_info = ContextInfo(
                    summary=summary,
                    conversations=[
                        {
                            "uuid": conv.uuid,
                            "timestamp": conv.timestamp.isoformat(sep=" ", timespec="microseconds"),
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
            result_rows, new_rows = run_sql_write(
                lambda: self._persist_conversations(db, user_id, character_id, conversation_data, commit)
            )
            self._append_conversations_to_cache(redis, user_id, character_id, new_rows)
            return [conv["uuid"] for conv in result_rows]
        except ConversationIdentityConflict:
            db.rollback()
            raise
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
            retained_context_count = run_sql_write(
                lambda: self._persist_compaction(
                    db,
                    user_id,
                    character_id,
                    new_summary,
                    keep_recent_count,
                    expected_context_count,
                    commit,
                )
            )
            if retained_context_count is not None:
                self._update_compaction_cache(
                    redis,
                    user_id,
                    character_id,
                    new_summary,
                    retained_context_count,
                )
            return retained_context_count is not None
        except Exception as e:
            logger.error(f"compact_conversation_context error: {e}")
            db.rollback()
            return False
        finally:
            db.close()

    def get_cognitive_maintenance_progress(self, user_id: str, *, character_id: str) -> str | None:
        """Return the last conversation covered by successful cognitive maintenance."""
        db = self._new_session()
        try:
            context = (
                db.query(ConversationContext.maintenance_entry_id)
                .filter(
                    ConversationContext.user_id == user_id,
                    ConversationContext.character_id == character_id,
                )
                .first()
            )
            return context[0] if context is not None else None
        finally:
            db.close()

    def advance_cognitive_maintenance_progress(
        self,
        user_id: str,
        *,
        character_id: str,
        expected_entry_id: str | None,
        new_entry_id: str,
    ) -> bool:
        """Atomically advance maintenance progress when its expected predecessor still matches.

        The target must be a conversation for the same user and character.  A
        target earlier than the expected predecessor is rejected in the same
        SQL statement, so callers cannot move an already advanced marker back.
        """
        if not isinstance(new_entry_id, str) or not new_entry_id or new_entry_id == expected_entry_id:
            return False
        if expected_entry_id is not None and not isinstance(expected_entry_id, str):
            return False

        db = self._new_session()
        try:

            def _write() -> bool:
                result = db.execute(
                    text("""
                    UPDATE conversation_contexts
                    SET maintenance_entry_id = :new_entry_id
                    WHERE user_id = :user_id
                      AND character_id = :character_id
                      AND (
                          (:expected_entry_id IS NULL AND maintenance_entry_id IS NULL)
                          OR maintenance_entry_id = :expected_entry_id
                      )
                      AND EXISTS (
                          SELECT 1
                          FROM conversations AS target
                          WHERE target.uuid = :new_entry_id
                            AND target.user_id = :user_id
                            AND target.character_id = :character_id
                      )
                      AND (
                          :expected_entry_id IS NULL
                          OR EXISTS (
                              SELECT 1
                              FROM conversations AS current
                              JOIN conversations AS target
                                ON target.uuid = :new_entry_id
                               AND target.user_id = :user_id
                               AND target.character_id = :character_id
                              WHERE current.uuid = :expected_entry_id
                                AND current.user_id = :user_id
                                AND current.character_id = :character_id
                                AND (
                                    target.timestamp > current.timestamp
                                    OR (target.timestamp = current.timestamp AND target.uuid > current.uuid)
                                )
                          )
                      )
                        """),
                    {
                        "user_id": user_id,
                        "character_id": character_id,
                        "expected_entry_id": expected_entry_id,
                        "new_entry_id": new_entry_id,
                    },
                )
                if result.rowcount != 1:
                    return False
                db.commit()
                return True

            return run_sql_write(_write)
        except Exception as error:
            logger.error(f"advance_cognitive_maintenance_progress error: {error}")
            db.rollback()
            return False
        finally:
            db.close()

    def load_cognitive_maintenance_batch(
        self, user_id: str, *, character_id: str, previous_progress: str | None
    ) -> CognitiveMaintenanceBatch | None:
        """Load the frozen recovery input for one uncommitted predecessor."""
        db = self._new_session()
        try:
            context = (
                db.query(ConversationContext.maintenance_entry_id)
                .filter(ConversationContext.user_id == user_id, ConversationContext.character_id == character_id)
                .first()
            )
            if context is None or context[0] != previous_progress:
                return None
            record = self._find_cognitive_maintenance_batch(db, user_id, character_id, previous_progress)
            return self._batch_contract(record) if record is not None else None
        finally:
            db.close()

    def create_or_load_cognitive_maintenance_batch(
        self,
        user_id: str,
        *,
        character_id: str,
        previous_progress: str | None,
        draft: CognitiveMaintenanceBatchDraft,
    ) -> CognitiveMaintenanceBatch:
        """Persist a complete attempt input once, returning the concurrent winner unchanged."""
        db = self._new_session()
        try:
            self._validate_cognitive_maintenance_draft(db, user_id, character_id, previous_progress, draft)
            existing = self._find_cognitive_maintenance_batch(db, user_id, character_id, previous_progress)
            if existing is not None:
                return self._batch_contract(existing)
            record = CognitiveMaintenanceBatchRecord(
                maintenance_id=str(uuid.uuid4()),
                user_id=user_id,
                character_id=character_id,
                previous_progress_key=self._progress_key(previous_progress),
                previous_entry_id=previous_progress,
                target_entry_id=draft.target_entry_id,
                covered_entry_ids=json.dumps(draft.covered_entry_ids, ensure_ascii=False),
                maintained_entry_ids=json.dumps(draft.maintained_entry_ids, ensure_ascii=False),
                candidates=json.dumps(draft.candidates, ensure_ascii=False, sort_keys=True),
                proposed_profile=draft.proposed_profile,
                input_digest=draft.input_digest,
                compaction_previous_summary=draft.compaction_previous_summary,
                compaction_covered_entry_ids=json.dumps(draft.compaction_covered_entry_ids, ensure_ascii=False),
                compaction_summary=draft.compaction_summary,
                compaction_expected_count=draft.compaction_expected_count,
            )
            db.add(record)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                record = self._find_cognitive_maintenance_batch(db, user_id, character_id, previous_progress)
                if record is None:
                    raise
            return self._batch_contract(record)
        finally:
            db.close()

    def commit_cognitive_maintenance(
        self,
        user_id: str,
        *,
        character_id: str,
        compaction,
        expected_progress: str | None,
        new_progress: str,
        maintenance_id: str | None = None,
    ) -> bool:
        """Commit compaction and progress in one SQL transaction, or leave both unchanged."""
        if not isinstance(new_progress, str) or not new_progress or new_progress == expected_progress:
            return False
        db = self._new_session()
        committed = False
        try:

            def _write() -> bool:
                nonlocal committed
                user = db.query(User).filter(User.uuid == user_id).first()
                if not self._can_commit_cognitive_maintenance(
                    db, user, user_id, character_id, compaction, expected_progress, new_progress, maintenance_id
                ):
                    return False
                context = self._get_or_create_conversation_context(db, user, character_id)
                if compaction is not None and not self._apply_maintenance_compaction(
                    db, context, user, character_id, compaction
                ):
                    return False
                context.maintenance_entry_id = new_progress
                db.commit()
                committed = True
                return True

            return run_sql_write(_write)
        except Exception as error:
            logger.error(f"commit_cognitive_maintenance error: {error}")
            db.rollback()
            return False
        finally:
            db.close()
            if committed:
                self._invalidate_context_cache(user_id, character_id)

    def _can_commit_cognitive_maintenance(
        self, db, user, user_id, character_id, compaction, expected_progress, new_progress, maintenance_id
    ) -> bool:
        if user is None:
            return False
        context = self._get_or_create_conversation_context(db, user, character_id)
        if context.maintenance_entry_id != expected_progress:
            return False
        if not self._batch_matches_commit(
            db, maintenance_id, user_id, character_id, compaction, expected_progress, new_progress
        ):
            return False
        return self._is_valid_progress_target(db, user_id, character_id, expected_progress, new_progress)

    @staticmethod
    def _batch_matches_commit(
        db, maintenance_id, user_id, character_id, compaction, expected_progress, new_progress
    ) -> bool:
        if maintenance_id is None:
            return True
        batch = db.query(CognitiveMaintenanceBatchRecord).filter_by(maintenance_id=maintenance_id).first()
        if batch is None or (
            batch.user_id,
            batch.character_id,
            batch.previous_entry_id,
            batch.target_entry_id,
        ) != (user_id, character_id, expected_progress, new_progress):
            return False
        return ConversationService._batch_compaction_matches(batch, compaction)

    @staticmethod
    def _batch_compaction_matches(batch, compaction) -> bool:
        has_frozen_compaction = batch.compaction_expected_count is not None
        if not has_frozen_compaction:
            return compaction is None
        if compaction is None:
            return False
        return (
            compaction.previous_summary.text == batch.compaction_previous_summary
            and compaction.covered_entry_ids == tuple(json.loads(batch.compaction_covered_entry_ids))
            and compaction.summary.text == batch.compaction_summary
        )

    @staticmethod
    def _progress_key(progress: str | None) -> str:
        return progress if progress is not None else ORIGIN_PROGRESS_KEY

    def _find_cognitive_maintenance_batch(self, db, user_id, character_id, previous_progress):
        return (
            db.query(CognitiveMaintenanceBatchRecord)
            .filter(
                CognitiveMaintenanceBatchRecord.user_id == user_id,
                CognitiveMaintenanceBatchRecord.character_id == character_id,
                CognitiveMaintenanceBatchRecord.previous_progress_key == self._progress_key(previous_progress),
            )
            .first()
        )

    @staticmethod
    def _batch_contract(record) -> CognitiveMaintenanceBatch:
        return CognitiveMaintenanceBatch(
            maintenance_id=record.maintenance_id,
            user_id=record.user_id,
            character_id=record.character_id,
            previous_progress_key=record.previous_progress_key,
            previous_entry_id=record.previous_entry_id,
            target_entry_id=record.target_entry_id,
            covered_entry_ids=tuple(json.loads(record.covered_entry_ids)),
            maintained_entry_ids=tuple(json.loads(record.maintained_entry_ids)),
            candidates=json.loads(record.candidates),
            proposed_profile=record.proposed_profile,
            input_digest=record.input_digest,
            compaction_previous_summary=record.compaction_previous_summary,
            compaction_covered_entry_ids=tuple(json.loads(record.compaction_covered_entry_ids)),
            compaction_summary=record.compaction_summary,
            compaction_expected_count=record.compaction_expected_count,
            created_at=record.created_at,
        )

    def _validate_cognitive_maintenance_draft(self, db, user_id, character_id, previous_progress, draft) -> None:
        entry_ids = self._draft_entry_ids(draft)
        context = (
            db.query(ConversationContext)
            .filter(ConversationContext.user_id == user_id, ConversationContext.character_id == character_id)
            .first()
        )
        if context is None or context.maintenance_entry_id != previous_progress:
            raise ValueError("认知维护 predecessor 已变化或上下文不存在")
        required = set(entry_ids)
        if previous_progress is not None:
            required.add(previous_progress)
        rows = (
            db.query(Conversation)
            .filter(
                Conversation.uuid.in_(required),
                Conversation.user_id == user_id,
                Conversation.character_id == character_id,
            )
            .all()
        )
        by_id = {row.uuid: row for row in rows}
        if set(by_id) != required:
            raise ValueError("认知维护批次包含不属于当前用户或角色的对话记录")
        self._validate_draft_entry_order(by_id, previous_progress, draft)
        self._validate_frozen_compaction_basis(db, context, user_id, character_id, draft)

    @staticmethod
    def _draft_entry_ids(draft) -> tuple[str, ...]:
        if not isinstance(draft, CognitiveMaintenanceBatchDraft):
            raise TypeError("draft 应为 CognitiveMaintenanceBatchDraft")
        entry_ids = (*draft.covered_entry_ids, *draft.maintained_entry_ids, draft.target_entry_id)
        if (
            not draft.target_entry_id
            or not draft.input_digest
            or any(not isinstance(value, str) or not value for value in entry_ids)
        ):
            raise ValueError("认知维护批次必须包含有效对话记录和输入摘要")
        if len(set(draft.covered_entry_ids)) != len(draft.covered_entry_ids):
            raise ValueError("被覆盖对话记录不能重复")
        return entry_ids

    @staticmethod
    def _validate_draft_entry_order(by_id, previous_progress, draft) -> None:
        target = by_id[draft.target_entry_id]
        previous = by_id.get(previous_progress) if previous_progress is not None else None
        if previous is not None and (target.timestamp, target.uuid) <= (previous.timestamp, previous.uuid):
            raise ValueError("认知维护目标不能倒退")
        for entry_id in (*draft.covered_entry_ids, *draft.maintained_entry_ids):
            entry = by_id[entry_id]
            if previous is not None and (entry.timestamp, entry.uuid) <= (previous.timestamp, previous.uuid):
                raise ValueError("认知维护记录必须位于 predecessor 之后")
            if (entry.timestamp, entry.uuid) > (target.timestamp, target.uuid):
                raise ValueError("认知维护记录不能超过目标记录")

    @staticmethod
    def _validate_frozen_compaction_basis(db, context, user_id, character_id, draft) -> None:
        fields = (
            draft.compaction_previous_summary,
            draft.compaction_covered_entry_ids,
            draft.compaction_summary,
            draft.compaction_expected_count,
        )
        if not any(field is not None and field != () for field in fields):
            return
        if (
            draft.compaction_previous_summary is None
            or draft.compaction_summary is None
            or draft.compaction_expected_count is None
            or draft.compaction_expected_count < 0
        ):
            raise ValueError("冻结压缩批次必须包含完整 basis")
        if context.context_summary != draft.compaction_previous_summary:
            raise ValueError("冻结压缩总结 basis 不匹配")
        if context.context_memory_count != draft.compaction_expected_count:
            raise ValueError("冻结压缩窗口计数 basis 不匹配")
        rows = (
            db.query(Conversation)
            .filter(Conversation.user_id == user_id, Conversation.character_id == character_id)
            .order_by(Conversation.timestamp.desc(), Conversation.uuid.desc())
            .limit(draft.compaction_expected_count)
            .all()
        )
        ordered_rows = tuple(reversed(rows))
        prefix = tuple(row.uuid for row in ordered_rows[: len(draft.compaction_covered_entry_ids)])
        if prefix != draft.compaction_covered_entry_ids:
            raise ValueError("冻结压缩记录 basis 不匹配")

    def _is_valid_progress_target(self, db, user_id, character_id, expected_progress, new_progress) -> bool:
        target = (
            db.query(Conversation)
            .filter(
                Conversation.uuid == new_progress,
                Conversation.user_id == user_id,
                Conversation.character_id == character_id,
            )
            .first()
        )
        if target is None:
            return False
        if expected_progress is None:
            return True
        previous = (
            db.query(Conversation)
            .filter(
                Conversation.uuid == expected_progress,
                Conversation.user_id == user_id,
                Conversation.character_id == character_id,
            )
            .first()
        )
        return previous is not None and (target.timestamp, target.uuid) > (previous.timestamp, previous.uuid)

    def _apply_maintenance_compaction(self, db, context, user, character_id, compaction) -> bool:
        if not all(hasattr(compaction, name) for name in ("previous_summary", "covered_entry_ids", "summary")):
            return False
        count = context.context_memory_count or 0
        covered = compaction.covered_entry_ids
        previous_summary = getattr(compaction.previous_summary, "text", None)
        new_summary = getattr(compaction.summary, "text", None)
        if not isinstance(covered, tuple) or not isinstance(previous_summary, str) or not isinstance(new_summary, str):
            return False
        if len(covered) > count or context.context_summary != previous_summary:
            return False
        rows = (
            db.query(Conversation)
            .filter(Conversation.user_id == user.uuid, Conversation.character_id == character_id)
            .order_by(Conversation.timestamp.desc(), Conversation.uuid.desc())
            .limit(count)
            .all()
        )
        entries = list(reversed(rows))
        if tuple(row.uuid for row in entries[: len(covered)]) != covered:
            return False
        context.context_summary = new_summary
        context.context_memory_count = count - len(covered)
        if character_id == "luotianyi":
            user.context_summary = new_summary
            user.context_memory_count = context.context_memory_count
        return True

    def _invalidate_context_cache(self, user_id: str, character_id: str) -> None:
        try:
            self._ensure_redis().delete(self._context_redis_key(user_id, character_id))
        except Exception as error:
            logger.warning(f"Failed to invalidate conversation context cache: {error}")

    def _persist_conversations(self, db, user_id, character_id, conversation_data, commit):
        user = db.query(User).filter(User.uuid == user_id).first()
        if not user:
            return [], []
        context = self._get_or_create_conversation_context(db, user, character_id)
        result_rows = []
        new_rows = []
        pending_by_uuid = {}
        requested_uuids = [item.uuid for item in conversation_data if item.uuid]
        existing_by_uuid = {
            row.uuid: row for row in db.query(Conversation).filter(Conversation.uuid.in_(requested_uuids)).all()
        }
        for item in conversation_data:
            item_uuid = item.uuid or str(uuid.uuid4())
            existing = existing_by_uuid.get(item_uuid) or pending_by_uuid.get(item_uuid)
            if existing is not None:
                self._validate_conversation_identity(existing, user_id, character_id, item)
                result_rows.append(self._conversation_dict(existing))
                continue
            conversation, row = self._conversation_row(db, user_id, character_id, item, item_uuid)
            pending_by_uuid[item_uuid] = conversation
            result_rows.append(row)
            new_rows.append(row)
        user.all_memory_count = (user.all_memory_count or 0) + len(new_rows)
        context.context_memory_count = (context.context_memory_count or 0) + len(new_rows)
        if character_id == "luotianyi":
            user.context_memory_count = context.context_memory_count
        if commit:
            db.commit()
        return result_rows, new_rows

    @staticmethod
    def _conversation_row(db, user_id, character_id, item, item_uuid):
        try:
            timestamp = datetime.fromisoformat(item.timestamp)
        except ValueError:
            timestamp = datetime.now()
        meta_data = None
        if item.data is not None:
            try:
                meta_data = json.dumps(item.data, ensure_ascii=False)
            except Exception as error:
                logger.error(f"Failed to serialize meta_data for user {user_id}: {error}")
        conversation = Conversation(
            user_id=user_id,
            character_id=character_id,
            timestamp=timestamp,
            source=item.source,
            content=item.content,
            type=item.type,
            meta_data=meta_data,
            uuid=item_uuid,
        )
        db.add(conversation)
        return conversation, {
            "uuid": conversation.uuid,
            "timestamp": item.timestamp,
            "source": item.source,
            "content": item.content,
            "type": item.type,
            "meta_data": meta_data,
        }

    @staticmethod
    def _conversation_dict(conversation):
        return {
            "uuid": conversation.uuid,
            "timestamp": conversation.timestamp.isoformat(sep=" ", timespec="microseconds"),
            "source": conversation.source,
            "content": conversation.content,
            "type": conversation.type,
            "meta_data": conversation.meta_data,
        }

    @staticmethod
    def _validate_conversation_identity(existing, user_id, character_id, item):
        matches = existing.user_id == user_id and existing.character_id == character_id and existing.type == item.type
        if matches and item.type == "audio":
            try:
                existing_media_id = json.loads(existing.meta_data or "{}").get("media_id")
            except (json.JSONDecodeError, TypeError):
                existing_media_id = None
            incoming_media_id = (item.data or {}).get("media_id")
            matches = existing_media_id == incoming_media_id and isinstance(incoming_media_id, str)
        if not matches:
            raise ConversationIdentityConflict(f"CONVERSATION_IDENTITY_CONFLICT: {existing.uuid}")

    def get_audio_media_id(self, user_id: str, conv_uuid: str) -> Optional[str]:
        """Return an owner-scoped audio media ID without exposing other rows."""
        db = self._new_session()
        try:
            conv = (
                db.query(Conversation)
                .filter(
                    Conversation.user_id == user_id,
                    Conversation.uuid == conv_uuid,
                    Conversation.type == "audio",
                )
                .first()
            )
            if not conv or not conv.meta_data:
                return None
            try:
                media_id = json.loads(conv.meta_data).get("media_id")
            except (json.JSONDecodeError, TypeError):
                return None
            return media_id if isinstance(media_id, str) and media_id.strip() else None
        finally:
            db.close()

    def reset_user_conversations(self, user_id: str) -> int:
        """Idempotently delete conversation rows and reset their SQL/cache state."""
        redis = self._ensure_redis()
        db = self._new_session()
        try:
            user = db.query(User).filter(User.uuid == user_id).first()
            if user is None:
                return 0
            character_ids = [
                value
                for (value,) in db.query(ConversationContext.character_id)
                .filter(ConversationContext.user_id == user_id)
                .all()
            ]
            deleted = db.query(Conversation).filter(Conversation.user_id == user_id).delete(synchronize_session=False)
            db.query(CognitiveMaintenanceBatchRecord).filter(CognitiveMaintenanceBatchRecord.user_id == user_id).delete(
                synchronize_session=False
            )
            (
                db.query(ConversationContext)
                .filter(ConversationContext.user_id == user_id)
                .delete(synchronize_session=False)
            )
            user.context_memory_count = 0
            user.all_memory_count = 0
            user.context_summary = ""
            db.commit()
            redis.delete(f"user_context:{user_id}")
            for character_id in character_ids:
                redis.delete(self._context_redis_key(user_id, character_id))
            return deleted
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _append_conversations_to_cache(self, redis, user_id, character_id, rows):
        redis_key = self._context_redis_key(user_id, character_id)
        with redis.pipeline() as pipe:
            for _ in range(3):
                try:
                    pipe.watch(redis_key)
                    data: ContextInfo = self._decode_redis_value(pipe.get(redis_key))
                    if not data:
                        pipe.unwatch()
                        return
                    updated = ContextInfo(
                        summary=data.summary,
                        conversations=sorted(
                            [*data.conversations, *rows], key=lambda row: (row["timestamp"], row["uuid"])
                        ),
                        context_count=(data.context_count or 0) + len(rows),
                    )
                    pipe.multi()
                    pipe.setex(redis_key, 3600, updated)
                    pipe.execute()
                    return
                except WatchError:
                    continue

    def _persist_compaction(
        self, db, user_id, character_id, new_summary, keep_recent_count, expected_context_count, commit
    ):
        user = db.query(User).filter(User.uuid == user_id).first()
        if not user:
            return None
        context = self._get_or_create_conversation_context(db, user, character_id)
        current_count = context.context_memory_count or 0
        if expected_context_count is not None and current_count < expected_context_count:
            return None
        retained_count = keep_recent_count
        if expected_context_count is not None:
            retained_count += current_count - expected_context_count
        context.context_summary = new_summary
        context.context_memory_count = retained_count
        if character_id == "luotianyi":
            user.context_summary = new_summary
            user.context_memory_count = retained_count
        if commit:
            db.commit()
        return retained_count

    def _update_compaction_cache(self, redis, user_id, character_id, new_summary, retained_count):
        redis_key = self._context_redis_key(user_id, character_id)
        with redis.pipeline() as pipe:
            for _ in range(3):
                try:
                    pipe.watch(redis_key)
                    data: ContextInfo = self._decode_redis_value(pipe.get(redis_key))
                    if not data:
                        pipe.unwatch()
                        return
                    data.summary = new_summary
                    data.conversations = data.conversations[-retained_count:] if retained_count > 0 else []
                    data.context_count = retained_count
                    pipe.multi()
                    pipe.setex(redis_key, 3600, data)
                    pipe.execute()
                    return
                except WatchError:
                    continue

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
            query = db.query(Conversation).filter(Conversation.user_id == user_id)
            if character_id is not None:
                query = query.filter(Conversation.character_id == character_id)
            conversations = (
                query.order_by(Conversation.timestamp.asc(), Conversation.uuid.asc()).offset(start).limit(limit).all()
            )
            result = []
            for conv in conversations:
                result.append(
                    ConversationItem(
                        timestamp=conv.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                        source=conv.source,
                        content=conv.content,
                        type=conv.type,
                        data=conv.meta_data and json.loads(conv.meta_data) or None,
                        uuid=conv.uuid,
                    )
                )
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
        context_info: Optional[ContextInfo] = self._decode_redis_value(
            redis.get(self._context_redis_key(user_id, character_id))
        )
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
            conv = (
                db.query(Conversation)
                .filter(
                    Conversation.user_id == user_id,
                    Conversation.uuid == conv_uuid,
                    Conversation.type == "image",
                )
                .first()
            )

            if conv and conv.meta_data:
                try:
                    meta_data = json.loads(conv.meta_data)
                    return meta_data.get("image_server_path")
                except Exception as e:
                    logger.error(f"Failed to parse meta_data for conversation {conv_uuid}: {e}")
            return None
        finally:
            db.close()

    def get_image_media_id(self, user_id: str, conv_uuid: str) -> Optional[str]:
        """获取图片对话记录引用的永久媒体 ID。"""
        db = self._new_session()
        try:
            conv = (
                db.query(Conversation)
                .filter(
                    Conversation.user_id == user_id,
                    Conversation.uuid == conv_uuid,
                    Conversation.type == "image",
                )
                .first()
            )
            if not conv or not conv.meta_data:
                return None
            try:
                media_id = json.loads(conv.meta_data).get("media_id")
            except (json.JSONDecodeError, TypeError):
                return None
            return media_id if isinstance(media_id, str) and media_id.strip() else None
        finally:
            db.close()

    def update_image_client_path(self, user_id: str, conv_uuid: str, new_client_path: str) -> bool:
        """更新图片的客户端路径。"""
        db = self._new_session()
        try:

            def _write() -> bool:
                conv = (
                    db.query(Conversation)
                    .filter(
                        Conversation.user_id == user_id,
                        Conversation.uuid == conv_uuid,
                        Conversation.type == "image",
                    )
                    .first()
                )

                if conv and conv.meta_data:
                    meta_data = json.loads(conv.meta_data)
                    meta_data["image_client_path"] = new_client_path
                    conv.meta_data = json.dumps(meta_data, ensure_ascii=False)
                    db.commit()
                    return True
                return False

            success = run_sql_write(_write)
            if not success:
                logger.warning(
                    f"Conversation with uuid {conv_uuid} not found for user {user_id} when updating image client path."
                )
            return success
        except Exception as e:
            logger.error(f"Failed to update image client path for conversation {conv_uuid}: {e}")
            db.rollback()
            return False
        finally:
            db.close()
