"""
Memory Search Module
--------------------
负责记忆的检索（Recall）。
核心难点在于如何根据用户模糊的输入，精确召回相关记忆。
"""

from ..utils.logger import get_logger
from ..utils.llm.prompt_manager import PromptManager
from ..utils.llm.llm_module import LLMModule
from typing import Tuple, Dict, List, Any
from ..database.database_service import VectorStore
import asyncio
import time
import re
from ..plugins.music.singing_manager import SingingManager
from sqlalchemy.orm import Session

# Citywalk search cache: data changes at most daily, 1h TTL is safe
_citywalk_cache_lock = asyncio.Lock()
_citywalk_cache_ts: float = 0.0
_citywalk_cache_data: list = []  # List[Tuple[float, str, str]]
_CITYWALK_CACHE_TTL: float = 3600.0


class MemorySearcher:
    def __init__(self, config: Dict[str, Any], prompt_manager: PromptManager):
        
        self.logger = get_logger(__name__)
        self.config = config
        self.llm = LLMModule(config["llm_module"], prompt_manager)
        self.max_k_vector_entities = config.get("max_k_vector_entities", 5)
        self.default_threshold = float(config.get("vector_score_threshold", 0.46))
        self.max_k_graph_entities = config.get("max_k_graph_entities", 3)

    async def search_memories_for_topic(
        self,
        vector_store: VectorStore,
        user_id: str,
        queries: List[str],
        k: int = 5,
        score_threshold: float = 0.60,
    ) -> List[str]:
        """面向 TopicReplier 的直接检索接口：混合检索并按分数截断。"""
        if not queries:
            return []
        
        async def search_with_thres(
            user_id: str,
            q: str,
            k: int,
            score_threshold: float,
            prefix: str = None,
            timestamp_keys: List[str] = None,
        ) -> List[Tuple[float, str, str]]:
            results = await vector_store.search(user_id, q, k=k)
            hits = []
            for doc, score in results:
                if score < score_threshold:
                    continue
                timestamp = ""
                meta = doc.get_metadata() if hasattr(doc, "get_metadata") else {}
                if isinstance(meta, dict):
                    for key in timestamp_keys or ["timestamp"]:
                        timestamp = str(meta.get(key) or "").strip()
                        if timestamp:
                            break
                # Multi-key: use metadata.value (actual memory fact) rather than content (search key)
                content = (meta.get("value", "") if isinstance(meta, dict) else "").strip()
                if not content:
                    content = doc.get_content().strip() if hasattr(doc, "get_content") else ""
                if not content:
                    continue
                rendered = f"在{timestamp}, {content}" if timestamp else content
                if prefix:
                    rendered = f"{prefix} {rendered}"
                # Dedup by value_id so multiple key-docs for same memory collapse to one
                value_id = str(meta.get("value_id", "") if isinstance(meta, dict) else "").strip()
                if not value_id:
                    value_id = str(getattr(doc, "id", "") or rendered)
                hits.append((score, value_id, rendered))
            return hits

        scored_hits: List[Tuple[float, str, str]] = []

        async def search_task(
            q: str,
            source: str,
            user_id_for_search: str,
            threshold: float,
            prefix: str = None,
            timestamp_keys: List[str] = None,
        ) -> Tuple[str, str, List[Tuple[float, str, str]]]:
            hits = await search_with_thres(
                user_id_for_search,
                q,
                max(1, k),
                threshold,
                prefix=prefix,
                timestamp_keys=timestamp_keys,
            )
            return q, source, hits

        pending_tasks: List[asyncio.Task] = []
        for query in queries:
            q = (query or "").strip()
            if not q:
                continue
            pending_tasks.append(asyncio.create_task(search_task(q, "user", user_id, score_threshold)))

        # Citywalk: single cached search per call, not N per-query searches
        global _citywalk_cache_ts, _citywalk_cache_data
        now = time.monotonic()
        if now - _citywalk_cache_ts >= _CITYWALK_CACHE_TTL:
            async with _citywalk_cache_lock:
                # double-check after acquiring lock
                if now - _citywalk_cache_ts >= _CITYWALK_CACHE_TTL:
                    citywalk_q = next((q.strip() for q in queries if q and q.strip()), "")
                    if citywalk_q:
                        _citywalk_cache_data = await search_with_thres(
                            "__citywalk__",
                            citywalk_q,
                            max(1, k),
                            min(score_threshold + 0.1, 0.88),
                            prefix="城市漫步记忆",
                            timestamp_keys=["citywalk_date", "timestamp"],
                        )
                        self.logger.debug(f"Citywalk cache refreshed, got {len(_citywalk_cache_data)} hits")
                    _citywalk_cache_ts = now
        scored_hits.extend(_citywalk_cache_data)

        for finished_task in asyncio.as_completed(pending_tasks):
            try:
                q, source, hits = await finished_task
                self.logger.debug(f"{source} vector search for query '{q}' completed with {len(hits)} hits")
                scored_hits.extend(hits)
            except Exception as exc:
                self.logger.debug(f"Memory search task failed: {exc}")

        if not scored_hits:
            return []

        # 先按分数降序，再按 value_id 去重（多Key共享同一 value_id）。
        scored_hits.sort(key=lambda x: x[0], reverse=True)
        dedup: List[str] = []
        seen_value_ids = set()
        for _, value_id, text in scored_hits:
            if value_id in seen_value_ids:
                continue
            seen_value_ids.add(value_id)
            dedup.append(text)
            if len(dedup) >= k:
                break

        return dedup

