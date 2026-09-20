"""Strict canonical-first intentional-memory commits."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, uuid5

from src.domain.memory_record import MemoryRecord as DomainMemoryRecord
from src.domain.memory_record import MemoryType, MemoryVisibility
from src.domain.memory_type import MemoryUpdateCommand
from src.infrastructure.persistence.database.vector_store import Document, VectorStore
from src.utils.asyncio_helpers import run_sync_owned
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.infrastructure.persistence.database.services.memory_store import MemoryStore


logger = get_logger("MemoryWriter")
_LEGACY_OWNER_CHARACTER_ID = "luotianyi"
_USER_FACT_NAMESPACE = "agent-luotianyi:user-fact"


class CanonicalMemoryCommitError(RuntimeError):
    """规范记忆正本未可靠提交时抛出。"""


class MemoryVectorCommitError(RuntimeError):
    """向量投影未返回可链接标识时抛出。"""


class IntentionalMemoryCommitMixin:
    """Commit canonical memory before its vector projection and compensate failures."""

    config: dict[str, Any]

    async def commit_user_memory(
        self,
        vector_store: VectorStore,
        memory_store: MemoryStore,
        user_id: str,
        content: str,
        owner_character_id: str = "luotianyi",
        commit: bool = True,
    ) -> tuple[str, bool]:
        """写入用户事实或返回现有规范记录标识；第二项表示本次是否新写入。"""
        text = (content or "").strip()
        if not text:
            return "", False

        threshold = float(self.config.get("user_memory_dedup_threshold", 0.72))
        existing_id = await self._similar_user_memory_id(
            vector_store,
            memory_store,
            user_id,
            text,
            threshold,
            owner_character_id,
        )
        if existing_id is not None:
            logger.debug(f"Skip duplicate user_memory for user {user_id}: {text[:50]}")
            return existing_id, False

        record_id = self._user_fact_record_id(owner_character_id, user_id, text)
        record = DomainMemoryRecord(
            id=record_id,
            owner_character_id=owner_character_id,
            subject_user_id=user_id,
            memory_type=MemoryType.USER_FACT,
            visibility=MemoryVisibility.PRIVATE,
            source="chat",
            content=text,
        )
        created = await self._write_canonical_record(memory_store, record, commit)
        if not created:
            return record_id, False

        await self._write_update(memory_store, user_id, text, record_id, commit)
        await self._project_record(vector_store, memory_store, record, commit)
        return record_id, True

    @staticmethod
    async def _write_canonical_record(
        memory_store: MemoryStore,
        record: DomainMemoryRecord,
        commit: bool,
    ) -> bool:
        written_record_id = await run_sync_owned(
            memory_store.write_agent_memory_record,
            record,
            chunk_texts=[],
            embedding_ids=[],
            commit=commit,
        )
        if written_record_id:
            return True
        existing_record = await run_sync_owned(memory_store.get_agent_memory_record, record.id)
        if existing_record is not None and await run_sync_owned(
            memory_store.agent_memory_record_has_embeddings,
            record.id,
        ):
            return False
        raise CanonicalMemoryCommitError("canonical memory commit failed")

    @staticmethod
    async def _write_update(
        memory_store: MemoryStore,
        user_id: str,
        text: str,
        record_id: str,
        commit: bool,
    ) -> None:
        update_cmd = MemoryUpdateCommand(type="write_user_memory", content=text, uuid=None)
        try:
            await run_sync_owned(memory_store.write_memory_update, user_id, update_cmd, commit=commit)
        except Exception:
            if commit:
                await run_sync_owned(memory_store.delete_agent_memory_record, record_id, commit=commit)
            raise

    @staticmethod
    async def _project_record(
        vector_store: VectorStore,
        memory_store: MemoryStore,
        record: DomainMemoryRecord,
        commit: bool,
    ) -> None:
        today = time.strftime("%Y-%m-%d")
        doc = Document(
            content=record.content,
            metadata={
                "source": "memory_writer",
                "timestamp": today,
                "event_date": today,
                "memory_type": "user_memory",
                "user_id": record.subject_user_id,
                "owner_character_id": record.owner_character_id,
            },
        )
        ids: list[str] = []
        try:
            ids = await run_sync_owned(vector_store.add_documents, [doc])
            if not ids:
                raise MemoryVectorCommitError("memory vector commit returned no identifier")
            await run_sync_owned(
                memory_store.link_agent_memory_embeddings,
                record.id,
                chunk_texts=[record.content],
                embedding_ids=ids,
                commit=commit,
            )
        except Exception:
            if ids:
                await run_sync_owned(vector_store.delete_documents, ids)
            if commit:
                await run_sync_owned(memory_store.delete_agent_memory_record, record.id, commit=commit)
            raise

    async def _similar_user_memory_id(
        self,
        vector_store: VectorStore,
        memory_store: MemoryStore,
        user_id: str,
        content: str,
        threshold: float,
        owner_character_id: str,
    ) -> str | None:
        """返回相似用户事实的现有规范记录标识，没有命中时返回 None。"""
        where = self._user_memory_where(user_id, owner_character_id)
        results = await vector_store.search(user_id, content, k=5, where=where)
        for doc, score in results:
            metadata = doc.get_metadata() if hasattr(doc, "get_metadata") else {}
            if metadata.get("memory_type") != "user_memory":
                continue
            if not self._owner_matches(metadata.get("owner_character_id"), owner_character_id):
                continue
            if score < threshold:
                continue
            identifier = str(getattr(doc, "id", "") or "")
            if not identifier:
                continue
            record = await run_sync_owned(memory_store.get_agent_memory_record_by_embedding_id, identifier)
            if record is not None:
                return record.id
        return None

    def _user_fact_record_id(self, owner_character_id: str, user_id: str, content: str) -> str:
        key = "\x1f".join((owner_character_id, user_id, self._normalize_text(content)))
        return str(uuid5(NAMESPACE_URL, f"{_USER_FACT_NAMESPACE}:{key}"))

    def _owner_matches(self, stored_owner: Any, owner_character_id: str) -> bool:
        if stored_owner == owner_character_id:
            return True
        return stored_owner is None and owner_character_id == _LEGACY_OWNER_CHARACTER_ID

    def _user_memory_where(self, user_id: str, owner_character_id: str) -> dict[str, Any]:
        if owner_character_id == _LEGACY_OWNER_CHARACTER_ID:
            return {"user_id": user_id, "memory_type": "user_memory"}
        return {
            "user_id": user_id,
            "memory_type": "user_memory",
            "owner_character_id": owner_character_id,
        }
