"""
Memory Write Module
-------------------
负责记忆的生成与写入（Generation/Storage）。
核心在于将非结构化的对话流转化为结构化、易于检索的知识片段。
"""

import json
from typing import List, Dict, Any
from src.utils.logger import get_logger
from src.system.database.vector_store import VectorStore, Document
from src.utils.llm.llm_module import LLMModule
import time
import asyncio
from src.domain.memory_record import MemoryRecord as DomainMemoryRecord
from src.domain.memory_record import MemoryType, MemoryVisibility

from src.domain.memory_type import MemoryUpdateCommand

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.system.database.memory_store import MemoryStore


logger = get_logger("MemoryWriter")


class MemoryWriter:
    def __init__(self, config: Dict[str, Any], llm_module: LLMModule):
        self.config = config
        self.llm = llm_module

    async def process_interaction(
        self,
        vector_store: VectorStore,
        memory_store: "MemoryStore",
        user_id: str,
        history: str,
        current_dialogue: str = "",
        related_memories: List[str] | None = None,
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
        result: Dict[str, Any] = {
            "payload": memory_payload,
            "items": [],
        }

        if user_items:
            # Single de-dup pass for all user memory items
            seen_texts = await self._batch_check_user_memory_dups(
                vector_store, user_id, user_items
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
        related_memories: List[str],
    ) -> Dict[str, Any]:
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
        except Exception as e:
            if response:
                logger.warning(
                    "Error generating memory payload: "
                    f"{e}; raw_response_excerpt={json.dumps(self._response_excerpt(response), ensure_ascii=False)}"
                )
            else:
                logger.warning(f"Error generating memory payload: {e}")
            return empty_payload

    def _response_excerpt(self, response: str, limit: int = 1000) -> Dict[str, Any]:
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

    def _parse_memory_json_response(self, response: str) -> Dict[str, List[str]]:
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
            raise ValueError("memory payload must be a JSON object")

        user_memory = data.get("user_memory", [])
        event_memory = data.get("event_memory", [])

        if not isinstance(user_memory, list) or not isinstance(event_memory, list):
            raise ValueError("user_memory/event_memory must be lists")

        def _clean_items(items: List[Any]) -> List[str]:
            cleaned: List[str] = []
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
        memory_store: "MemoryStore",
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
        ids = await asyncio.to_thread(vector_store.add_documents, [doc])
        update_cmd = MemoryUpdateCommand(type="write_user_memory", content=text, uuid=ids[0] if ids else None)
        await asyncio.to_thread(memory_store.write_memory_update, user_id, update_cmd, commit=commit)
        await asyncio.to_thread(
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
        memory_store: "MemoryStore",
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
        ids = await asyncio.to_thread(vector_store.add_documents, [doc])
        update_cmd = MemoryUpdateCommand(type="write_event_memory", content=text, uuid=ids[0] if ids else None)
        await asyncio.to_thread(memory_store.write_memory_update, user_id, update_cmd, commit=commit)
        await asyncio.to_thread(
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
    ) -> bool:
        results = await vector_store.search(user_id, content, k=5)
        for doc, score in results:
            metadata = doc.get_metadata() if hasattr(doc, "get_metadata") else {}
            if metadata.get("memory_type") != "user_memory":
                continue
            if score >= threshold:
                return True
        return False

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
        items: List[str],
    ) -> set:
        """Batch check: collect all existing user_memory text in one search pass."""
        seen = set()
        if not items:
            return seen
        # Search with the first item — it's representative enough to catch most duplicates.
        threshold = float(self.config.get("user_memory_dedup_threshold", 0.72))
        results = await vector_store.search(user_id, items[0], k=20)
        for doc, score in results:
            metadata = doc.get_metadata() if hasattr(doc, "get_metadata") else {}
            if metadata.get("memory_type") != "user_memory":
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
        items: List[str],
        event_date: str,
    ) -> set:
        """Batch check: collect all same-day event_memory text in one search pass."""
        seen = set()
        if not items:
            return seen
        results = await vector_store.search(user_id, items[0], k=20)
        target_norm = None
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
