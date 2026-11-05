from __future__ import annotations

import asyncio
from datetime import date
from typing import TYPE_CHECKING, Any, Dict, List, Tuple

from src.domain import MemoryContext, MemoryHit
from src.domain.agent.maintenance import MaintenanceCandidate
from src.domain.memory_record import MemoryType, MemoryVisibility
from src.infrastructure.observability.retrieval_timing import measure_retrieval, retrieval_phase
from src.infrastructure.persistence.database.vector_store import VectorStore

from .profile_updater import UserProfileUpdater
from .writer import MemoryWriter

if TYPE_CHECKING:
    from src.infrastructure.persistence.database import DatabaseManager
    from src.infrastructure.persistence.database.services.memory_store import MemoryStore


class AgentMemory:
    """Agent 的长期记忆适配入口，负责召回、写入和用户画像更新。

    这一层只接收业务参数，不再接收 db/redis/session。底层数据库连接和
    缓存生命周期交给 DatabaseManager 与 MemoryStore 统一管理。
    """

    def __init__(
        self,
        config: Dict[str, Any],
        llm_service,
        *,
        database_manager: "DatabaseManager",
        vector_store: VectorStore,
        owner_character_id: str = "luotianyi",
    ):
        self.config = config
        self.owner_character_id = owner_character_id
        self.database_manager = database_manager
        self.vector_store = vector_store
        self.memory_writer = MemoryWriter(
            config["memory_writer"],
            llm_service.register_llm_module(
                f"skill.cognitive_maintenance.extract.{owner_character_id}", config["memory_writer"]["llm_module"]
            ),
        )
        self.user_profile_updater = UserProfileUpdater(
            config["user_profile"],
            llm_service.register_llm_module(
                f"skill.cognitive_maintenance.profile.{owner_character_id}", config["user_profile"]["llm_module"]
            ),
        )

    def ensure_dependencies(self) -> None:
        """检查 Agent 记忆适配器依赖已经初始化。"""
        required = {
            "database_manager": self.database_manager,
            "vector_store": self.vector_store,
            "memory_writer": self.memory_writer,
            "user_profile_updater": self.user_profile_updater,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise RuntimeError(f"AgentMemory dependencies are missing: {', '.join(missing)}")
        if self.database_manager.memory_store is None:
            raise RuntimeError("AgentMemory dependency is missing: memory_store")

    @property
    def memory_store(self) -> "MemoryStore":
        """返回数据库层的记忆存储服务。"""
        memory_store = self.database_manager.memory_store
        if memory_store is None:
            raise RuntimeError("MemoryStore has not been initialized.")
        return memory_store

    async def citywalk_memory_on(self, day: date) -> MemoryContext:
        """从角色的漫步事件正本读取完整经历，不依赖向量相似度或虚拟用户身份。"""
        events = await asyncio.to_thread(
            self.database_manager.event_store.get_citywalk_events, self.owner_character_id, day
        )
        return MemoryContext(
            tuple(
                MemoryHit(
                    rendered_text=f"{day:%Y-%m-%d} {event['title']}：{event['description']}",
                    score=1.0,
                    query="/YesterdayCityWalk",
                    source="citywalk_event",
                    source_record_id=event["id"],
                )
                for event in events
            )
        )

    @measure_retrieval
    async def search_memory_context_for_topic(
        self,
        user_id: str,
        queries: List[str],
        similarity_threshold: float = 0.8,
        k: int = 3,
        *,
        include_user: bool = True,
        include_character: bool = True,
    ) -> MemoryContext:
        """按话题线索召回结构化记忆上下文。

        向量库只作为召回索引使用；命中向量后会批量回查 MemoryStore 中
        的规范记忆正本，并把正本挂到 MemoryHit 上。
        """
        if not queries:
            return MemoryContext()

        with retrieval_phase("authorization"):
            allowed_ids = await asyncio.to_thread(
                self.memory_store.get_scoped_embedding_ids,
                self.owner_character_id,
                user_id,
                include_user=include_user,
                include_character=include_character,
                legacy_ids=self._legacy_character_ids(),
            )

        candidate_hits = await self._search_candidates(
            user_id, queries, similarity_threshold, k, allowed_ids, include_user
        )
        vector_ids = [vector_id for _, _, vector_id, _, _ in candidate_hits if vector_id]
        with retrieval_phase("hydration"):
            records_by_vector_id = await asyncio.to_thread(
                self.memory_store.get_agent_memory_records_by_embedding_ids,
                vector_ids,
            )

        with retrieval_phase("materialization"):
            scored_hits = self._materialize_hits(
                candidate_hits, records_by_vector_id, user_id, include_user, include_character
            )
            return MemoryContext(self._top_distinct_hits(scored_hits, k))

    async def _search_candidates(
        self,
        user_id: str,
        queries: List[str],
        similarity_threshold: float,
        k: int,
        allowed_ids: list[str],
        include_user: bool,
    ) -> List[Tuple[float, str, str, Any, str]]:
        candidates: List[Tuple[float, str, str, Any, str]] = []
        for query in queries:
            q = (query or "").strip()
            if not q:
                continue
            if not include_user and not allowed_ids:
                continue
            embedding = await self.vector_store.embed_query(q)
            results = (
                await self.vector_store.search(user_id, q, k=max(1, k), query_embedding=embedding)
                if include_user
                else []
            )
            if allowed_ids:
                results += await self.vector_store.search(
                    user_id, q, k=max(1, k), ids=allowed_ids, where=None, query_embedding=embedding
                )
            for doc, score in results:
                if score < similarity_threshold:
                    continue
                content = doc.get_content().strip() if hasattr(doc, "get_content") else ""
                if not content:
                    continue
                vector_id = str(getattr(doc, "id", "") or "")
                candidates.append((score, q, vector_id, doc, content))
        return candidates

    def _materialize_hits(
        self,
        candidates: List[Tuple[float, str, str, Any, str]],
        records_by_vector_id: dict[str, Any],
        user_id: str,
        include_user: bool,
        include_character: bool,
    ) -> List[Tuple[float, str, MemoryHit]]:
        scored_hits: List[Tuple[float, str, MemoryHit]] = []
        for score, query, vector_id, doc, content in candidates:
            record = records_by_vector_id.get(vector_id) if vector_id else None
            metadata = doc.get_metadata()
            if not self._can_read(record, metadata, user_id, include_user, include_character):
                continue
            rendered = self._render_memory_hit(record, content, doc)
            dedup_key = record.id if record else vector_id or rendered
            scored_hits.append(
                (
                    score,
                    dedup_key,
                    MemoryHit(
                        rendered_text=rendered,
                        score=score,
                        query=query,
                        source="canonical_vector" if record else "legacy_vector",
                        record=record,
                        vector_id=vector_id or None,
                    ),
                )
            )
        return scored_hits

    def _legacy_character_ids(self) -> set[str]:
        """受控旧格式适配：仅信任部署者明确列出的旧角色事件正本 ID。"""
        return set(self.config.get("legacy_character_memory_ids", {}).get(self.owner_character_id, ()))

    def _can_read(self, record, metadata, user_id, include_user, include_character) -> bool:
        if record is None:
            return (
                "memory_scope" not in metadata
                and include_user
                and metadata.get("user_id") == user_id
                and metadata.get("owner_character_id", "luotianyi") == self.owner_character_id
            )
        if record.owner_character_id != self.owner_character_id:
            return False
        if record.subject_user_id is None:
            return include_character and record.visibility is MemoryVisibility.CHARACTER_PRIVATE
        if record.id in self._legacy_character_ids() and record.memory_type is MemoryType.INTERACTION_EVENT:
            return include_character and record.subject_user_id == self.owner_character_id
        return include_user and record.subject_user_id == user_id

    @staticmethod
    def _top_distinct_hits(scored_hits: List[Tuple[float, str, MemoryHit]], k: int) -> tuple[MemoryHit, ...]:
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
        return tuple(hits)

    async def write_topic_memories(
        self,
        user_id: str,
        history: str,
        current_dialogue: str = "",
        related_memories: List[str] | None = None,
        commit: bool = True,
    ) -> Dict[str, Any]:
        """从一轮对话中抽取可长期保存的用户事实和事件记忆。"""
        return await self.memory_writer.process_interaction(
            vector_store=self.vector_store,
            memory_store=self.memory_store,
            user_id=user_id,
            history=history,
            current_dialogue=current_dialogue,
            related_memories=related_memories or [],
            owner_character_id=self.owner_character_id,
            commit=commit,
        )

    async def extract_maintenance_candidates(
        self, *, history: str, current_dialogue: str
    ) -> tuple[MaintenanceCandidate, ...]:
        return await self.memory_writer.extract_maintenance_candidates(
            history=history,
            current_dialogue=current_dialogue,
        )

    async def write_maintenance_candidates(
        self,
        *,
        user_id: str,
        maintenance_id: str,
        candidates: tuple[MaintenanceCandidate, ...],
    ) -> None:
        await self.memory_writer.write_maintenance_candidates(
            vector_store=self.vector_store,
            memory_store=self.memory_store,
            user_id=user_id,
            owner_character_id=self.owner_character_id,
            maintenance_id=maintenance_id,
            candidates=candidates,
        )

    async def propose_user_profile(self, *, history: dict[str, Any], current_profile: str) -> str | None:
        proposed = await self.user_profile_updater.update_profile(history=history, current_profile=current_profile)
        return proposed or None

    async def write_user_memory(
        self,
        user_id: str,
        content: str,
        commit: bool = True,
    ) -> bool:
        """直接写入一条用户事实记忆。"""
        return await self.memory_writer.write_user_memory(
            vector_store=self.vector_store,
            memory_store=self.memory_store,
            user_id=user_id,
            content=content,
            owner_character_id=self.owner_character_id,
            commit=commit,
        )

    async def write_event_memory(
        self,
        user_id: str,
        content: str,
        commit: bool = True,
    ) -> bool:
        """直接写入一条互动事件记忆。"""
        return await self.memory_writer.write_event_memory(
            vector_store=self.vector_store,
            memory_store=self.memory_store,
            user_id=user_id,
            content=content,
            owner_character_id=self.owner_character_id,
            commit=commit,
        )

    async def update_user_profile_by_context(
        self,
        user_id: str,
        context: Dict[str, Any],
        commit: bool = True,
    ) -> str | None:
        """根据长期上下文更新用户画像。"""
        current_profile = self.database_manager.conversation_service.get_user_description(user_id) or ""
        new_profile = await self.user_profile_updater.update_profile(
            history=context,
            current_profile=current_profile,
        )
        if not new_profile:
            return None

        await asyncio.to_thread(
            self.database_manager.conversation_service.update_user_description,
            user_id,
            new_profile,
            commit,
        )
        return new_profile

    def _render_memory_hit(self, record, fallback_content: str, doc) -> str:
        """将规范记忆或旧向量文档渲染成可进入提示词的文本。"""
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
