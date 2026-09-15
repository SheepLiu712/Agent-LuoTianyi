"""
Memory Write Module
-------------------
负责记忆的生成与写入（Generation/Storage）。
核心在于将非结构化的对话流转化为结构化、易于检索的知识片段。
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, uuid5

from src.domain.memory_record import MemoryRecord as DomainMemoryRecord
from src.domain.memory_record import MemoryType, MemoryVisibility
from src.domain.memory_type import MemoryUpdateCommand
from src.system.database.vector_store import Document, VectorStore
from src.utils.asyncio_helpers import run_sync_owned
from src.utils.llm.llm_module import LLMModule
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.system.database.services.memory_store import MemoryStore


logger = get_logger("MemoryWriter")


_LEGACY_OWNER_CHARACTER_ID = "luotianyi"
_USER_FACT_NAMESPACE = "agent-luotianyi:user-fact"


class CanonicalMemoryCommitError(RuntimeError):
    """规范记忆正本未可靠提交时抛出。"""


class MemoryVectorCommitError(RuntimeError):
    """向量投影未返回可链接标识时抛出。"""


class MemoryWriter:
    def __init__(self, config: dict[str, Any], llm_module: LLMModule):
        self.config = config
        self.llm = llm_module

    async def process_interaction(
        self,
        vector_store: VectorStore,
        memory_store: MemoryStore,
        user_id: str,
        history: str,
        current_dialogue: str = "",
        related_memories: list[str] | None = None,
        owner_character_id: str = "luotianyi",
        commit: bool = True
    ):
        """
        分析最近的交互，提取有价值的信息存入记忆库。
        """
        memory_payload = await self._extract_knowledge(
            history,
            current_dialogue=current_dialogue,
            related_memories=related_memories or [],
        )

        # Batch dedup: do one search per memory type for all items,
        # then write only non-duplicate items.
        user_items = memory_payload.get("user_memory", [])
        event_items = memory_payload.get("event_memory", [])
        result: dict[str, Any] = {
            "payload": memory_payload,
            "items": [],
        }

        if user_items:
            # Single de-dup pass for all user memory items
            seen_texts = await self._batch_check_user_memory_dups(
                vector_store, user_id, user_items, owner_character_id,
            )
            for content in user_items:
                text = (content or "").strip()
                if not text or text in seen_texts:
                    result["items"].append({
                        "memory_type": "user_memory",
                        "content": text,
                        "status": "skipped_duplicate_or_empty",
                    })
                    continue
                seen_texts.add(text)
                written = await self.write_user_memory(
                    vector_store=vector_store,
                    memory_store=memory_store,
                    user_id=user_id,
                    content=content,
                    owner_character_id=owner_character_id,
                    commit=commit,
                )
                result["items"].append({
                    "memory_type": "user_memory",
                    "content": text,
                    "status": "written" if written else "skipped",
                })

        if event_items:
            today = time.strftime("%Y-%m-%d")
            seen_texts = await self._batch_check_event_memory_dups(
                vector_store, user_id, event_items, today
            )
            for content in event_items:
                text = (content or "").strip()
                normalized_text = self._normalize_text(text)
                if not text or normalized_text in seen_texts:
                    result["items"].append({
                        "memory_type": "event_memory",
                        "content": text,
                        "status": "skipped_duplicate_or_empty",
                        "event_date": today,
                    })
                    continue
                seen_texts.add(normalized_text)
                written = await self.write_event_memory(
                    vector_store=vector_store,
                    memory_store=memory_store,
                    user_id=user_id,
                    content=content,
                    owner_character_id=owner_character_id,
                    commit=commit,
                )
                result["items"].append({
                    "memory_type": "event_memory",
                    "content": text,
                    "status": "written" if written else "skipped",
                    "event_date": today,
                })
        return result

    async def _extract_knowledge(
        self,
        history: str,
        current_dialogue: str,
        related_memories: list[str],
    ) -> dict[str, Any]:
        """
        使用 LLM 从对话历史中提取有价值的记忆内容。

        返回格式：
        {
            "user_memory": [str, ...],
            "event_memory": [str, ...],
        }

        Args:
            history: 最近的对话历史
        """
        history_str = history
        empty_payload = {"user_memory": [], "event_memory": []}
        response = ""
        try:
            response = await self.llm.generate_response(
                use_json=True,
                history=history_str,
                current_dialogue=current_dialogue,
                related_memories=related_memories,
            )
            payload = self._parse_memory_json_response(response)
            logger.debug(f"Memory extraction payload: {payload}")
            return payload
        except Exception as e:  # noqa: BLE001 - 旧 LLM 边界将任意提取失败降级为空载荷。
            if response:
                logger.warning(
                    "Error generating memory payload: "
                    f"{e}; raw_response_excerpt={json.dumps(self._response_excerpt(response), ensure_ascii=False)}"
                )
            else:
                logger.warning(f"Error generating memory payload: {e}")
            return empty_payload

    def _response_excerpt(self, response: str, limit: int = 1000) -> dict[str, Any]:
        raw = str(response or "")
        if len(raw) <= limit * 2:
            return {
                "length": len(raw),
                "text": raw,
            }
        return {
            "length": len(raw),
            "prefix": raw[:limit],
            "suffix": raw[-limit:],
        }

    def _parse_memory_json_response(self, response: str) -> dict[str, list[str]]:
        """解析 LLM 返回的 JSON，兼容 ```json 代码块包装。"""
        raw = (response or "").strip()

        if raw.startswith("```"):
            lines = raw.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            raw = "\n".join(lines).strip()

        data = json.loads(raw)
        if not isinstance(data, dict):
            raise TypeError("memory payload must be a JSON object")

        user_memory = data.get("user_memory", [])
        event_memory = data.get("event_memory", [])

        if not isinstance(user_memory, list) or not isinstance(event_memory, list):
            raise TypeError("user_memory/event_memory must be lists")

        def _clean_items(items: list[Any]) -> list[str]:
            cleaned: list[str] = []
            for item in items:
                text = str(item or "").strip()
                if text:
                    cleaned.append(text)
            return cleaned

        return {
            "user_memory": _clean_items(user_memory),
            "event_memory": _clean_items(event_memory),
        }

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
        _, committed = await self.commit_user_memory(
            vector_store=vector_store, memory_store=memory_store, user_id=user_id,
            content=content, owner_character_id=owner_character_id, commit=commit,
        )
        return committed

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
            vector_store, memory_store, user_id, text, threshold, owner_character_id,
        )
        if existing_id is not None:
            logger.debug(f"Skip duplicate user_memory for user {user_id}: {text[:50]}")
            return existing_id, False

        today = time.strftime("%Y-%m-%d")
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
        written_record_id = await run_sync_owned(
            memory_store.write_agent_memory_record,
            record,
            chunk_texts=[],
            embedding_ids=[],
            commit=commit,
        )
        if not written_record_id:
            existing_record = await run_sync_owned(memory_store.get_agent_memory_record, record_id)
            if existing_record is not None and await run_sync_owned(
                memory_store.agent_memory_record_has_embeddings, record_id,
            ):
                return record_id, False
            raise CanonicalMemoryCommitError("canonical memory commit failed")

        update_cmd = MemoryUpdateCommand(type="write_user_memory", content=text, uuid=None)
        try:
            await run_sync_owned(memory_store.write_memory_update, user_id, update_cmd, commit=commit)
        except Exception:
            if commit:
                await run_sync_owned(memory_store.delete_agent_memory_record, record_id, commit=commit)
            raise

        doc = Document(
            content=text,
            metadata={
                "source": "memory_writer",
                "timestamp": today,
                "event_date": today,
                "memory_type": "user_memory",
                "user_id": user_id,
                "owner_character_id": owner_character_id,
            },
        )
        ids: list[str] = []
        try:
            ids = await run_sync_owned(vector_store.add_documents, [doc])
            if not ids:
                raise MemoryVectorCommitError("memory vector commit returned no identifier")
            await run_sync_owned(
                memory_store.link_agent_memory_embeddings,
                record_id,
                chunk_texts=[text],
                embedding_ids=ids,
                commit=commit,
            )
        except Exception:
            if ids:
                await run_sync_owned(vector_store.delete_documents, ids)
            if commit:
                await run_sync_owned(memory_store.delete_agent_memory_record, record_id, commit=commit)
            raise
        if not ids:
            raise MemoryVectorCommitError("memory vector commit returned no identifier")
        return record_id, True

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
        self,
        vector_store: VectorStore,
        user_id: str,
        content: str,
        threshold: float,
        owner_character_id: str = "luotianyi",
    ) -> bool:
        return await self._similar_user_memory_id(
            vector_store, None, user_id, content, threshold, owner_character_id,
        ) is not None

    async def _similar_user_memory_id(
        self, vector_store: VectorStore, memory_store: MemoryStore | None,
        user_id: str, content: str, threshold: float,
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
            if score >= threshold:
                identifier = str(getattr(doc, "id", "") or "")
                if not identifier or memory_store is None:
                    continue
                record = await run_sync_owned(memory_store.get_agent_memory_record_by_embedding_id, identifier)
                if record is None:
                    continue
                return record.id
        return None

    async def _is_same_day_duplicate_event_memory(
        self,
        vector_store: VectorStore,
        user_id: str,
        content: str,
        event_date: str,
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
        owner_character_id: str,
    ) -> set:
        """Batch check: collect all existing user_memory text in one search pass."""
        seen = set()
        if not items:
            return seen
        # Search with the first item — it's representative enough to catch most duplicates.
        threshold = float(self.config.get("user_memory_dedup_threshold", 0.72))
        results = await vector_store.search(
            user_id, items[0], k=20, where=self._user_memory_where(user_id, owner_character_id),
        )
        for doc, score in results:
            metadata = doc.get_metadata() if hasattr(doc, "get_metadata") else {}
            if metadata.get("memory_type") != "user_memory":
                continue
            if not self._owner_matches(metadata.get("owner_character_id"), owner_character_id):
                continue
            if score >= threshold:
                content = doc.get_content() if hasattr(doc, "get_content") else ""
                if content:
                    seen.add(content.strip())
        return seen

    async def _batch_check_event_memory_dups(
        self,
        vector_store: VectorStore,
        user_id: str,
        items: list[str],
        event_date: str,
    ) -> set:
        """Batch check: collect all same-day event_memory text in one search pass."""
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

    def _user_fact_record_id(self, owner_character_id: str, user_id: str, content: str) -> str:
        key = "\x1f".join((owner_character_id, user_id, self._normalize_text(content)))
        return str(uuid5(NAMESPACE_URL, f"{_USER_FACT_NAMESPACE}:{key}"))

    def _owner_matches(self, stored_owner: Any, owner_character_id: str) -> bool:
        if stored_owner == owner_character_id:
            return True
        return stored_owner is None and owner_character_id == _LEGACY_OWNER_CHARACTER_ID

    def _user_memory_where(self, user_id: str, owner_character_id: str) -> dict[str, Any]:
        if owner_character_id == _LEGACY_OWNER_CHARACTER_ID:
            return {
                "user_id": user_id,
                "memory_type": "user_memory",
            }
        return {
            "user_id": user_id,
            "memory_type": "user_memory",
            "owner_character_id": owner_character_id,
        }
