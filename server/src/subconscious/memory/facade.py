from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Tuple, TYPE_CHECKING

from src.domain import MemoryContext, MemoryHit
from src.system.database.vector_store import VectorStore
from src.subconscious.memory.memory_write import MemoryWriter
from src.subconscious.memory.user_profile_updater import UserProfileUpdater

if TYPE_CHECKING:
    from src.system.database import DatabaseManager
    from src.system.database.memory_store import MemoryStore


class SubconsciousMemory:
    """角色潜意识的记忆入口，负责召回、写入和用户画像更新。

    这一层只接收业务参数，不再接收 db/redis/session。底层数据库连接和
    缓存生命周期交给 DatabaseManager 与 MemoryStore 统一管理。
    """

    def __init__(
        self,
        config: Dict[str, Any],
        llm_modules: Dict[str, Any],
        *,
        database_manager: "DatabaseManager",
        vector_store: VectorStore,
        owner_character_id: str = "luotianyi",
    ):
        self.config = config
        self.owner_character_id = owner_character_id
        self.database_manager = database_manager
        self.vector_store = vector_store
        self.memory_writer = MemoryWriter(config["memory_writer"], llm_modules["memory_writer"])
        self.user_profile_updater = UserProfileUpdater(
            config["user_profile"],
            llm_modules["user_profile_updater"],
        )

    def ensure_dependencies(self) -> None:
        """检查潜意识记忆子系统依赖已经初始化。"""
        required = {
            "database_manager": self.database_manager,
            "vector_store": self.vector_store,
            "memory_writer": self.memory_writer,
            "user_profile_updater": self.user_profile_updater,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise RuntimeError(f"SubconsciousMemory dependencies are missing: {', '.join(missing)}")
        if self.database_manager.memory_store is None:
            raise RuntimeError("SubconsciousMemory dependency is missing: memory_store")

    @property
    def memory_store(self) -> "MemoryStore":
        """返回数据库层的记忆存储服务。"""
        memory_store = self.database_manager.memory_store
        if memory_store is None:
            raise RuntimeError("MemoryStore has not been initialized.")
        return memory_store

    async def search_memory_context_for_topic(
        self,
        user_id: str,
        queries: List[str],
        similarity_threshold: float = 0.8,
        k: int = 3,
    ) -> MemoryContext:
        """按话题线索召回结构化记忆上下文。

        向量库只作为召回索引使用；命中向量后会批量回查 MemoryStore 中
        的规范记忆正本，并把正本挂到 MemoryHit 上。
        """
        if not queries:
            return MemoryContext()

        candidate_hits: List[Tuple[float, str, str, Any, str]] = []
        vector_ids: List[str] = []
        for query in queries:
            q = (query or "").strip()
            if not q:
                continue
            results = await self.vector_store.search(user_id, q, k=max(1, k))
            for doc, score in results:
                if score < similarity_threshold:
                    continue
                content = doc.get_content().strip() if hasattr(doc, "get_content") else ""
                if not content:
                    continue

                vector_id = str(getattr(doc, "id", "") or "")
                if vector_id:
                    vector_ids.append(vector_id)
                candidate_hits.append((score, q, vector_id, doc, content))

        records_by_vector_id = await asyncio.to_thread(
            self.memory_store.get_agent_memory_records_by_embedding_ids,
            vector_ids,
        )

        scored_hits: List[Tuple[float, str, MemoryHit]] = []
        for score, query, vector_id, doc, content in candidate_hits:
            record = records_by_vector_id.get(vector_id) if vector_id else None
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
        current_profile = self.database_manager.get_user_description(user_id) or ""
        new_profile = await self.user_profile_updater.update_profile(
            history=context,
            current_profile=current_profile,
        )
        if not new_profile:
            return None

        await asyncio.to_thread(
            self.database_manager.update_user_description,
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
