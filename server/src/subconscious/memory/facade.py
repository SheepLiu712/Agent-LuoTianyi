from __future__ import annotations

from typing import Any, Dict, List, Tuple

from sqlalchemy.orm import Session

from src.system.database.vector_store import VectorStore
from src.system.database.database_service import get_agent_memory_record_by_embedding_id
from src.system.database.redis_buffer import RedisBuffer
from src.domain import MemoryContext, MemoryHit
from src.utils.llm.prompt_manager import PromptManager
from src.subconscious.memory.memory_manager import MemoryManager
from src.subconscious.memory.update_service import MemoryUpdateService


class SubconsciousMemory:
    """Facade for memory read/write/profile behavior.

    The old memory package remains as implementation detail for now. New code
    should depend on this facade so memory can later be replaced by canonical
    MemoryRecord + vector/graph projections without changing callers.
    """

    def __init__(
        self,
        config: Dict[str, Any],
        prompt_manager: PromptManager,
        owner_character_id: str = "luotianyi",
    ):
        self.owner_character_id = owner_character_id
        self.legacy_manager = MemoryManager(config, prompt_manager)
        self.updates = MemoryUpdateService(self)

    @property
    def memory_searcher(self):
        return self.legacy_manager.memory_searcher

    @property
    def memory_writer(self):
        return self.legacy_manager.memory_writer

    @property
    def user_profile_updater(self):
        return self.legacy_manager.user_profile_updater

    async def get_knowledge(
        self,
        db: Session,
        redis: RedisBuffer,
        vector_store: VectorStore,
        knowledge_db: Session,
        user_id: str,
        user_input: str,
        history: str,
    ) -> List[str]:
        return await self.legacy_manager.get_knowledge(
            db=db,
            redis=redis,
            vector_store=vector_store,
            knowledge_db=knowledge_db,
            user_id=user_id,
            user_input=user_input,
            history=history,
        )

    async def search_memories_for_topic(
        self,
        vector_store: VectorStore,
        user_id: str,
        queries: List[str],
        similarity_threshold: float = 0.8,
        k: int = 3,
    ) -> List[str]:
        return await self.legacy_manager.search_memories_for_topic(
            vector_store=vector_store,
            user_id=user_id,
            queries=queries,
            similarity_threshold=similarity_threshold,
            k=k,
        )

    async def search_memory_context_for_topic(
        self,
        db: Session,
        vector_store: VectorStore,
        user_id: str,
        queries: List[str],
        similarity_threshold: float = 0.8,
        k: int = 3,
    ) -> MemoryContext:
        """Recall typed memory hits for conscious planning.

        Vector documents are treated as index chunks. When a vector id can be
        mapped to a canonical MemoryRecord, the hit carries that record;
        otherwise it remains a legacy vector hit.
        """
        if not queries:
            return MemoryContext()

        scored_hits: List[Tuple[float, str, MemoryHit]] = []
        for query in queries:
            q = (query or "").strip()
            if not q:
                continue
            results = await vector_store.search(user_id, q, k=max(1, k))
            for doc, score in results:
                if score < similarity_threshold:
                    continue
                content = doc.get_content().strip() if hasattr(doc, "get_content") else ""
                if not content:
                    continue

                vector_id = str(getattr(doc, "id", "") or "")
                record = get_agent_memory_record_by_embedding_id(db, vector_id) if vector_id else None
                rendered = self._render_memory_hit(record, content, doc)
                dedup_key = record.id if record else vector_id or rendered
                scored_hits.append(
                    (
                        score,
                        dedup_key,
                        MemoryHit(
                            rendered_text=rendered,
                            score=score,
                            query=q,
                            source="canonical_vector" if record else "legacy_vector",
                            record=record,
                            vector_id=vector_id or None,
                        ),
                    )
                )

        scored_hits.sort(key=lambda item: item[0], reverse=True)
        hits: List[MemoryHit] = []
        seen_keys = set()
        seen_text = set()
        for _, dedup_key, hit in scored_hits:
            if dedup_key in seen_keys or hit.rendered_text in seen_text:
                continue
            seen_keys.add(dedup_key)
            seen_text.add(hit.rendered_text)
            hits.append(hit)
            if len(hits) >= k:
                break
        return MemoryContext(tuple(hits))

    def _render_memory_hit(self, record, fallback_content: str, doc) -> str:
        if record is not None:
            timestamp = ""
            if record.happened_at:
                timestamp = record.happened_at.strftime("%Y-%m-%d")
            elif record.created_at:
                timestamp = record.created_at.strftime("%Y-%m-%d")
            content = (record.summary or record.content or fallback_content).strip()
            return f"在{timestamp}, {content}" if timestamp else content

        metadata = doc.get_metadata() if hasattr(doc, "get_metadata") else {}
        timestamp = ""
        if isinstance(metadata, dict):
            timestamp = str(metadata.get("timestamp") or metadata.get("event_date") or "").strip()
        return f"在{timestamp}, {fallback_content}" if timestamp else fallback_content

    async def post_process_interaction(
        self,
        db: Session,
        redis: RedisBuffer,
        vector_store: VectorStore,
        user_id: str,
        history: str,
        current_dialogue: str = "",
        related_memories: List[str] | None = None,
        commit: bool = True,
    ) -> None:
        await self.legacy_manager.post_process_interaction(
            db=db,
            redis=redis,
            vector_store=vector_store,
            user_id=user_id,
            history=history,
            current_dialogue=current_dialogue,
            related_memories=related_memories or [],
            owner_character_id=self.owner_character_id,
            commit=commit,
        )

    async def write_user_memory(
        self,
        db: Session,
        redis: RedisBuffer,
        vector_store: VectorStore,
        user_id: str,
        content: str,
        commit: bool = True,
    ) -> bool:
        return await self.legacy_manager.write_user_memory(
            db=db,
            redis=redis,
            vector_store=vector_store,
            user_id=user_id,
            content=content,
            owner_character_id=self.owner_character_id,
            commit=commit,
        )

    async def write_event_memory(
        self,
        db: Session,
        redis: RedisBuffer,
        vector_store: VectorStore,
        user_id: str,
        content: str,
        commit: bool = True,
    ) -> bool:
        return await self.legacy_manager.write_event_memory(
            db=db,
            redis=redis,
            vector_store=vector_store,
            user_id=user_id,
            content=content,
            owner_character_id=self.owner_character_id,
            commit=commit,
        )

    async def get_username(self, db: Session, redis: RedisBuffer, user_id: str) -> str:
        return await self.legacy_manager.get_username(db=db, redis=redis, user_id=user_id)

    async def update_user_profile_by_topic(
        self,
        db: Session,
        redis: RedisBuffer,
        user_id: str,
        history: str,
        current_dialogue: str,
        commit: bool = True,
    ) -> str:
        return await self.legacy_manager.update_user_profile_by_topic(
            db=db,
            redis=redis,
            user_id=user_id,
            history=history,
            current_dialogue=current_dialogue,
            commit=commit,
        )

    async def update_user_profile_by_context(
        self,
        db: Session,
        redis: RedisBuffer,
        user_id: str,
        context: Dict[str, Any],
        commit: bool = True,
    ) -> str | None:
        return await self.legacy_manager.update_user_profile_by_context(
            db=db,
            redis=redis,
            user_id=user_id,
            context=context,
            commit=commit,
        )
