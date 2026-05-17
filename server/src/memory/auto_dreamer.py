"""
Auto Dreamer Module
-------------------
负责凌晨对当天记忆进行总结和结构化，将碎片关联为事件。

每 N 天凌晨执行一次：
1. 对每个活跃用户，取出当日写入的记忆片段
2. LLM 聚类：将同一事件的碎片归组
3. 每个事件组生成名称和总结摘要
4. 将事件以 event_summary 类型写回 ChromaDB
"""

import json
import time
from typing import Any, Dict, List, Optional

from ..utils.logger import get_logger
from ..utils.llm.llm_module import LLMModule
from ..utils.llm.prompt_manager import PromptManager
from ..database.vector_store import VectorStore, Document

logger = get_logger("AutoDreamer")


class AutoDreamer:
    """记忆自动整理器：将当日记忆碎片聚类为结构化事件。"""

    def __init__(self, config: Dict[str, Any], prompt_manager: PromptManager):
        self.config = config
        self.llm = LLMModule(config["llm_module"], prompt_manager)
        self.logger = logger

    async def run_for_all_active_users(self, vector_store: VectorStore) -> None:
        """遍历今日有记忆写入的用户，逐一整理。"""
        today = time.strftime("%Y-%m-%d")
        user_ids = self._collect_active_user_ids(vector_store, today)
        if not user_ids:
            self.logger.info("No active users found for auto dreamer")
            return

        for user_id in user_ids:
            try:
                await self.run_for_user(vector_store, user_id, today)
            except Exception as e:
                self.logger.error(f"Auto dreamer failed for user {user_id}: {e}")

    async def run_for_user(
        self, vector_store: VectorStore, user_id: str, today: Optional[str] = None
    ) -> None:
        """对单个用户的今日记忆进行聚类和总结。"""
        today = today or time.strftime("%Y-%m-%d")

        fragments = self._fetch_today_memories(vector_store, user_id, today)
        if not fragments:
            self.logger.debug(f"No memories today for user {user_id}")
            return

        events = await self._cluster_into_events(fragments)
        if not events:
            self.logger.debug(f"No clusterable events for user {user_id}")
            return

        for event in events:
            self._write_event_summary(vector_store, user_id, event, today)

        self.logger.info(
            f"Auto dreamer created {len(events)} event summaries for user {user_id}"
        )

    def _collect_active_user_ids(
        self, vector_store: VectorStore, today: str
    ) -> List[str]:
        """从 ChromaDB 找出今天有记忆写入的用户 ID。"""
        try:
            docs = vector_store.get_documents({"timestamp": today})
            seen = set()
            for doc in docs:
                meta = doc.get_metadata() if hasattr(doc, "get_metadata") else {}
                uid = meta.get("user_id", "")
                if uid:
                    seen.add(uid)
            return list(seen)
        except Exception as e:
            self.logger.error(f"Failed to collect active user IDs: {e}")
            return []

    def _fetch_today_memories(
        self, vector_store: VectorStore, user_id: str, today: str
    ) -> List[Dict[str, Any]]:
        """取出用户今天的 user_memory 和 event_memory，返回碎片列表。"""
        fragments: List[Dict[str, Any]] = []

        try:
            docs = vector_store.get_documents(
                {"$and": [{"user_id": user_id}, {"timestamp": today}]}
            )
            for doc in docs:
                meta = doc.get_metadata() if hasattr(doc, "get_metadata") else {}
                memory_type = meta.get("memory_type", "")
                if memory_type not in ("user_memory", "event_memory"):
                    continue
                value = (
                    meta.get("value", "")
                    if isinstance(meta, dict)
                    else ""
                )
                if not value:
                    continue
                fragments.append(
                    {
                        "value_id": meta.get("value_id", ""),
                        "type": memory_type,
                        "content": value,
                    }
                )
        except Exception as e:
            self.logger.error(f"Failed to fetch today memories for {user_id}: {e}")

        # De-duplicate by value_id (same memory written via multiple keys)
        seen_ids = set()
        unique: List[Dict[str, Any]] = []
        for f in fragments:
            vid = f.get("value_id", "")
            if vid and vid in seen_ids:
                continue
            if vid:
                seen_ids.add(vid)
            unique.append(f)

        return unique

    async def _cluster_into_events(
        self, fragments: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """调用 LLM 将零散记忆碎片聚类为事件。"""
        if len(fragments) < 2:
            return []

        # Build fragment list text
        lines = []
        for i, f in enumerate(fragments):
            lines.append(
                f"[{i}] type={f.get('type', 'unknown')}, content={f.get('content', '')}"
            )
        fragment_text = "\n".join(lines)

        try:
            response = await self.llm.generate_response(
                use_json=True,
                memory_fragments=fragment_text,
            )
            payload = self._parse_response(response)
            events = payload.get("events", [])
            if not events:
                return []

            # Map fragment_indices to value_ids and filter out sparse events
            result = []
            for ev in events:
                indices = ev.get("fragment_indices", [])
                matched = [
                    fragments[i] for i in indices if 0 <= i < len(fragments)
                ]
                if len(matched) < 2:
                    continue  # skip events with only 1 fragment
                result.append(
                    {
                        "event_name": (ev.get("event_name") or "").strip(),
                        "summary": (ev.get("summary") or "").strip(),
                        "fragments": matched,
                    }
                )
            return result
        except Exception as e:
            self.logger.warning(f"Failed to cluster memories: {e}")
            return []

    def _parse_response(self, response: str) -> Dict[str, Any]:
        """解析 LLM 返回的 JSON，兼容 ```json 代码块包装。"""
        raw = (response or "").strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            raw = "\n".join(lines).strip()
        return json.loads(raw) if raw else {"events": []}

    def _write_event_summary(
        self,
        vector_store: VectorStore,
        user_id: str,
        event: Dict[str, Any],
        today: str,
    ) -> None:
        """将聚类后的事件写为 event_summary 类型文档。"""
        event_name = event.get("event_name", "未命名事件")
        summary = event.get("summary", "")
        fragments = event.get("fragments", [])

        if not summary:
            return

        value_text = f"[{event_name}] {summary}"
        fragment_value_ids = [
            f.get("value_id", "") for f in fragments if f.get("value_id")
        ]

        # Generate keys for this event summary
        keys = [
            f"今天发生了什么事件？",
            f"{event_name}",
            summary[:30],
        ]

        docs = []
        for key in keys:
            docs.append(
                Document(
                    content=key,
                    metadata={
                        "source": "auto_dreamer",
                        "timestamp": today,
                        "event_date": today,
                        "memory_type": "event_summary",
                        "user_id": user_id,
                        "value": value_text,
                        "keys": keys,
                        "fragment_value_ids": fragment_value_ids,
                    },
                )
            )
        vector_store.add_documents(docs)
        self.logger.debug(
            f"Wrote event_summary '{event_name}' for user {user_id}"
        )
