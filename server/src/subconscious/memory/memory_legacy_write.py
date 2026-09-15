"""Legacy subconscious memory writes and vector-only deduplication."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from src.domain.memory_record import MemoryRecord as DomainMemoryRecord
from src.domain.memory_record import MemoryType, MemoryVisibility
from src.domain.memory_type import MemoryUpdateCommand
from src.system.database.vector_store import Document, VectorStore
from src.utils.asyncio_helpers import run_sync_owned
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.system.database.services.memory_store import MemoryStore


logger = get_logger("MemoryWriter")


class LegacyMemoryWriteMixin:
    """Preserve the pre-intentional-memory public write behavior."""

    config: dict[str, Any]

    async def write_user_memory(
        self,
        vector_store: VectorStore,
        memory_store: MemoryStore,
        user_id: str,
        content: str,
        owner_character_id: str = "luotianyi",
        commit: bool = True,
    ) -> bool:
        """写入用户长期记忆：若存在相似记忆则跳过。"""
        text = (content or "").strip()
        if not text:
            return False

        threshold = float(self.config.get("user_memory_dedup_threshold", 0.72))
        is_dup = await self._has_similar_user_memory(vector_store, user_id, text, threshold)
        if is_dup:
            logger.debug(f"Skip duplicate user_memory for user {user_id}: {text[:50]}")
            return False

        today = time.strftime("%Y-%m-%d")
        doc = Document(
            content=text,
            metadata={
                "source": "memory_writer",
                "timestamp": today,
                "event_date": today,
                "memory_type": "user_memory",
                "user_id": user_id,
            },
        )
        ids = await run_sync_owned(vector_store.add_documents, [doc])
        update_cmd = MemoryUpdateCommand(
            type="write_user_memory", content=text, uuid=ids[0] if ids else None,
        )
        await run_sync_owned(
            memory_store.write_memory_update, user_id, update_cmd, commit=commit,
        )
        await run_sync_owned(
            memory_store.write_agent_memory_record,
            DomainMemoryRecord(
                owner_character_id=owner_character_id,
                subject_user_id=user_id,
                memory_type=MemoryType.USER_FACT,
                visibility=MemoryVisibility.PRIVATE,
                source="chat",
                content=text,
                metadata={
                    "legacy_update_type": update_cmd.type,
                    "legacy_vector_ids": ids or [],
                },
            ),
            embedding_ids=ids or [],
            commit=commit,
        )
        return True

    async def write_event_memory(
        self,
        vector_store: VectorStore,
        memory_store: MemoryStore,
        user_id: str,
        content: str,
        owner_character_id: str = "luotianyi",
        commit: bool = True,
    ) -> bool:
        """写入事件记忆：日期不同直接写入；同日期且内容完全一致则跳过。"""
        text = (content or "").strip()
        if not text:
            return False

        today = time.strftime("%Y-%m-%d")
        if await self._is_same_day_duplicate_event_memory(vector_store, user_id, text, today):
            logger.debug(f"Skip same-day duplicate event_memory for user {user_id}: {text[:50]}")
            return False

        doc = Document(
            content=text,
            metadata={
                "source": "memory_writer",
                "timestamp": today,
                "event_date": today,
                "memory_type": "event_memory",
                "user_id": user_id,
            },
        )
        ids = await run_sync_owned(vector_store.add_documents, [doc])
        update_cmd = MemoryUpdateCommand(type="write_event_memory", content=text, uuid=ids[0] if ids else None)
        await run_sync_owned(memory_store.write_memory_update, user_id, update_cmd, commit=commit)
        await run_sync_owned(
            memory_store.write_agent_memory_record,
            DomainMemoryRecord(
                owner_character_id=owner_character_id,
                subject_user_id=user_id,
                memory_type=MemoryType.INTERACTION_EVENT,
                visibility=MemoryVisibility.PRIVATE,
                source="chat",
                content=text,
                metadata={
                    "event_date": today,
                    "legacy_update_type": update_cmd.type,
                    "legacy_vector_ids": ids or [],
                },
            ),
            embedding_ids=ids or [],
            commit=commit,
        )
        return True

    async def _has_similar_user_memory(
        self, vector_store: VectorStore, user_id: str, content: str, threshold: float,
    ) -> bool:
        results = await vector_store.search(user_id, content, k=5)
        for doc, score in results:
            metadata = doc.get_metadata() if hasattr(doc, "get_metadata") else {}
            if metadata.get("memory_type") == "user_memory" and score >= threshold:
                return True
        return False

    async def _is_same_day_duplicate_event_memory(
        self, vector_store: VectorStore, user_id: str, content: str, event_date: str,
    ) -> bool:
        results = await vector_store.search(user_id, content, k=10)
        target = self._normalize_text(content)
        for doc, _ in results:
            metadata = doc.get_metadata() if hasattr(doc, "get_metadata") else {}
            if metadata.get("memory_type") != "event_memory":
                continue
            if str(metadata.get("event_date") or metadata.get("timestamp") or "") != event_date:
                continue
            existing = self._normalize_text(doc.get_content() if hasattr(doc, "get_content") else "")
            if existing and existing == target:
                return True
        return False

    async def _batch_check_user_memory_dups(
        self,
        vector_store: VectorStore,
        user_id: str,
        items: list[str],
        owner_character_id: str | None = None,
    ) -> set:
        """Collect existing user-memory text in one search pass."""
        seen = set()
        if not items:
            return seen
        threshold = float(self.config.get("user_memory_dedup_threshold", 0.72))
        if owner_character_id is None:
            results = await vector_store.search(user_id, items[0], k=20)
        else:
            results = await vector_store.search(
                user_id, items[0], k=20,
                where=self._user_memory_where(user_id, owner_character_id),
            )
        for doc, score in results:
            metadata = doc.get_metadata() if hasattr(doc, "get_metadata") else {}
            if metadata.get("memory_type") != "user_memory":
                continue
            if owner_character_id is not None and not self._owner_matches(
                metadata.get("owner_character_id"), owner_character_id,
            ):
                continue
            if score >= threshold:
                existing = doc.get_content() if hasattr(doc, "get_content") else ""
                if existing:
                    seen.add(existing.strip())
        return seen

    async def _batch_check_event_memory_dups(
        self, vector_store: VectorStore, user_id: str, items: list[str], event_date: str,
    ) -> set:
        """Collect existing same-day event-memory text in one search pass."""
        seen = set()
        if not items:
            return seen
        results = await vector_store.search(user_id, items[0], k=20)
        for doc, _ in results:
            metadata = doc.get_metadata() if hasattr(doc, "get_metadata") else {}
            if metadata.get("memory_type") != "event_memory":
                continue
            doc_date = str(metadata.get("event_date") or metadata.get("timestamp") or "")
            if doc_date != event_date:
                continue
            existing = doc.get_content() if hasattr(doc, "get_content") else ""
            if existing:
                seen.add(self._normalize_text(existing))
        return seen

    def _normalize_text(self, text: str) -> str:
        return " ".join((text or "").strip().split())
