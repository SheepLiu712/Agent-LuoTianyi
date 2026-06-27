from __future__ import annotations

from typing import Any,  List, Callable, Dict, Optional, TYPE_CHECKING
from datetime import datetime
import json

from src.utils.logger import get_logger
from src.utils.llm_service import LLMModule, LLMService
from src.system.database.redis_buffer import RedisBuffer
from src.system.database.sql_database import (
    AgentMemoryRecord,
    MemoryChunkRecord,
    MemoryUpdateRecord,
)
from src.domain.memory_record import MemoryRecord as DomainMemoryRecord
from src.domain import MemoryUpdateCommand
from src.system.database.sql_writer import run_sql_write

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

class MemoryStore:
    """
    处理记忆服务的存储和检索操作。
    """

    def __init__(
        self, 
        config: Dict[str, Any], 
        sql_session_factory: Callable[[], Any], 
        redis_buffer: RedisBuffer,
        llm_module: Optional[Any] = None
    ):
        self.config = config
        self.logger = get_logger(__name__)
        self.sql_session_factory = sql_session_factory
        self._redis = redis_buffer
        self.llm_module = llm_module

    def create_llm_module(self, llm_service: LLMService):
        llm_module_config = self.config.get("llm_module")
        if not llm_module_config:
            raise ValueError("Missing 'llm_module' configuration for MemoryStore.")
        self.llm_module = llm_service.register_llm_module("MemoryStore", llm_module_config)

    # ——————————————————————————————————
    # 内部方法
    # ——————————————————————————————————

    def _ensure_redis(self) -> RedisBuffer:
        return self._redis

    def _new_session(self) -> Session:
        """创建一个新的 SQL 会话。调用者负责关闭。"""
        return self.sql_session_factory()

    def open_sql_session(self) -> Session:
        """Compatibility factory for legacy components not yet using manager methods."""
        return self._new_session()
    

    # ────────────────────────────────────────────
    # 记忆更新命令记录管理
    # ────────────────────────────────────────────

    def write_memory_update(self, user_id: str, memory_update: MemoryUpdateCommand, commit: bool = True) -> None:
        """向数据库中添加记忆更新命令记录，并更新 Redis 缓存。"""
        redis = self._ensure_redis()
        db = self._new_session()
        try:
            cmd_to_dict = {
                "uuid": memory_update.uuid,
                "content": memory_update.content,
                "type": memory_update.type,
            }

            def _write() -> None:
                record = MemoryUpdateRecord(
                    user_id=user_id,
                    update_command=json.dumps(cmd_to_dict, ensure_ascii=False),
                    created_at=datetime.now(),
                )
                db.add(record)
                if commit:
                    db.commit()

            run_sql_write(_write)

            # 更新 Redis 最近记忆更新缓存
            recent_update_key = f"user_recent_memory_update:{user_id}"
            raw_data = redis.get(recent_update_key)
            updates_list = json.loads(raw_data) if raw_data else []
            updates_list.append(cmd_to_dict)
            updates_list = updates_list[-10:]
            redis.setex(recent_update_key, 3600, json.dumps(updates_list, ensure_ascii=False))

        except Exception as e:
            self.logger.error(f"write_memory_update error: {e}")
            db.rollback()
        finally:
            db.close()

    def write_agent_memory_record(
        self,
        memory_record: DomainMemoryRecord,
        *,
        chunk_texts: Optional[List[str]] = None,
        embedding_ids: Optional[List[str]] = None,
        commit: bool = True,
    ) -> str:
        """持久化一条规范的记忆记录及其可选的向量 chunk。"""
        chunk_texts = chunk_texts or [memory_record.content]
        embedding_ids = embedding_ids or []

        db = self._new_session()
        try:
            def _write() -> str:
                row = AgentMemoryRecord(
                    id=memory_record.id,
                    owner_character_id=memory_record.owner_character_id,
                    subject_user_id=memory_record.subject_user_id,
                    memory_type=memory_record.memory_type.value,
                    visibility=memory_record.visibility.value,
                    source=memory_record.source,
                    content=memory_record.content,
                    summary=memory_record.summary,
                    importance=memory_record.importance,
                    confidence=memory_record.confidence,
                    emotional_valence=memory_record.emotional_valence,
                    happened_at=memory_record.happened_at,
                    created_at=memory_record.created_at,
                    last_accessed_at=memory_record.last_accessed_at,
                    meta_data=json.dumps(dict(memory_record.metadata or {}), ensure_ascii=False),
                )
                db.add(row)

                for index, chunk_text in enumerate(chunk_texts):
                    text = (chunk_text or "").strip()
                    if not text:
                        continue
                    db.add(MemoryChunkRecord(
                        memory_record_id=row.id,
                        chunk_text=text,
                        chunk_type="content",
                        embedding_id=embedding_ids[index] if index < len(embedding_ids) else None,
                    ))

                if commit:
                    db.commit()
                return row.id

            return run_sql_write(_write)
        except Exception as e:
            self.logger.error(f"write_agent_memory_record error: {e}")
            db.rollback()
            return ""
        finally:
            db.close()

    def get_agent_memory_record(self, memory_record_id: str) -> Optional[DomainMemoryRecord]:
        """根据 ID 读取一条记忆记录。"""
        db = self._new_session()
        try:
            row = db.query(AgentMemoryRecord).filter(AgentMemoryRecord.id == memory_record_id).first()
            if row is None:
                return None

            return self._domain_record_from_row(row)
        finally:
            db.close()

    def get_agent_memory_record_by_embedding_id(self, embedding_id: str) -> Optional[DomainMemoryRecord]:
        """根据向量索引 embedding_id 反查规范记忆记录。"""
        db = self._new_session()
        try:
            chunk = db.query(MemoryChunkRecord).filter(MemoryChunkRecord.embedding_id == embedding_id).first()
            if chunk is None:
                return None
            return self.get_agent_memory_record(chunk.memory_record_id)
        finally:
            db.close()

    def get_agent_memory_records_by_embedding_ids(
        self,
        embedding_ids: List[str],
    ) -> Dict[str, DomainMemoryRecord]:
        """批量根据向量索引 ID 反查规范记忆记录。

        返回值以 embedding_id 为键，避免记忆层为了每个向量命中反复打开
        Session。没有映射到正本的向量 ID 不会出现在结果中。
        """
        ids = [str(item).strip() for item in embedding_ids if str(item or "").strip()]
        if not ids:
            return {}

        db = self._new_session()
        try:
            chunks = (
                db.query(MemoryChunkRecord)
                .filter(MemoryChunkRecord.embedding_id.in_(ids))
                .all()
            )
            memory_ids = list({chunk.memory_record_id for chunk in chunks})
            if not memory_ids:
                return {}

            rows = (
                db.query(AgentMemoryRecord)
                .filter(AgentMemoryRecord.id.in_(memory_ids))
                .all()
            )
            records_by_id = {
                row.id: self._domain_record_from_row(row)
                for row in rows
            }
            return {
                chunk.embedding_id: records_by_id[chunk.memory_record_id]
                for chunk in chunks
                if chunk.embedding_id and chunk.memory_record_id in records_by_id
            }
        finally:
            db.close()

    def _domain_record_from_row(self, row: AgentMemoryRecord) -> DomainMemoryRecord:
        """将数据库行转换成领域层记忆对象。"""
        from src.domain.memory_record import MemoryType, MemoryVisibility

        try:
            metadata = json.loads(row.meta_data or "{}")
        except Exception:
            metadata = {}

        return DomainMemoryRecord(
            id=row.id,
            owner_character_id=row.owner_character_id,
            subject_user_id=row.subject_user_id,
            memory_type=MemoryType(row.memory_type),
            visibility=MemoryVisibility(row.visibility),
            source=row.source,
            content=row.content,
            summary=row.summary,
            importance=row.importance if row.importance is not None else 0.5,
            confidence=row.confidence if row.confidence is not None else 1.0,
            emotional_valence=row.emotional_valence,
            happened_at=row.happened_at,
            created_at=row.created_at,
            last_accessed_at=row.last_accessed_at,
            metadata=metadata,
        )

    def get_recent_memory_update_from_buffer(self, user_id: str) -> List[MemoryUpdateCommand]:
        """从 Redis 获取最近记忆更新列表。"""
        redis = self._ensure_redis()
        redis_key = f"user_recent_memory_update:{user_id}"
        raw_data = redis.get(redis_key)
        if not raw_data:
            self.prefill_buffer(user_id)
            raw_data = redis.get(redis_key)

        if raw_data:
            updates_list = json.loads(raw_data)
            return [
                MemoryUpdateCommand(
                    uuid=item.get("uuid"),
                    content=item.get("content"),
                    type=item.get("type"),
                )
                for item in updates_list
            ]
        return []
