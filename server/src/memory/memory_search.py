"""
Memory Search Module
--------------------
负责记忆的检索（Recall）。
核心难点在于如何根据用户模糊的输入，精确召回相关记忆。
"""

from ..utils.logger import get_logger
from ..plugins.music.knowledge_service import get_song_introduction, get_song_lyrics
from ..utils.llm.prompt_manager import PromptManager
from ..utils.llm.llm_module import LLMModule
from typing import Tuple, Dict, List, Any
from ..database.database_service import VectorStore
import asyncio 
import re
from ..plugins.music.singing_manager import SingingManager

from sqlalchemy.orm import Session


class MemorySearcher:
    def __init__(self, config: Dict[str, Any], prompt_manager: PromptManager, singing_manager: SingingManager):
        
        self.logger = get_logger(__name__)
        self.config = config
        self.llm = LLMModule(config["llm_module"], prompt_manager)
        self.max_k_vector_entities = config.get("max_k_vector_entities", 5)
        self.default_threshold = float(config.get("vector_score_threshold", 0.46))
        self.max_k_graph_entities = config.get("max_k_graph_entities", 3)
        self.singing_manager = singing_manager


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
                if hasattr(doc, "metadata") and isinstance(doc.metadata, dict):
                    for key in timestamp_keys or ["timestamp"]:
                        timestamp = str(doc.metadata.get(key) or "").strip()
                        if timestamp:
                            break
                content = doc.get_content().strip() if hasattr(doc, "get_content") else ""
                if not content:
                    continue
                rendered = f"在{timestamp}, {content}" if timestamp else content
                if prefix:
                    rendered = f"{prefix} {rendered}"
                doc_id = str(getattr(doc, "id", "") or rendered)
                hits.append((score, doc_id, rendered))
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
            pending_tasks.append(
                asyncio.create_task(
                    search_task(
                        q,
                        "citywalk",
                        "__citywalk__",
                        min(score_threshold + 0.1, 0.88),
                        prefix="城市漫步记忆",
                        timestamp_keys=["citywalk_date", "timestamp"],
                    )
                )
            )

        for finished_task in asyncio.as_completed(pending_tasks):
            try:
                q, source, hits = await finished_task
                self.logger.debug(f"{source} vector search for query '{q}' completed with {len(hits)} hits")
                scored_hits.extend(hits)
            except Exception as exc:
                self.logger.debug(f"Memory search task failed: {exc}")

        if not scored_hits:
            return []

        # 先按分数降序，再按 doc_id 去重。
        scored_hits.sort(key=lambda x: x[0], reverse=True)
        dedup: List[str] = []
        seen_doc_ids = set()
        seen_text = set()
        for _, doc_id, text in scored_hits:
            if doc_id in seen_doc_ids or text in seen_text:
                continue
            seen_doc_ids.add(doc_id)
            seen_text.add(text)
            dedup.append(text)
            if len(dedup) >= k:
                break

        return dedup

    async def search_song_facts_for_topic(
        self,
        knowledge_db: Session,
        constraints: List[str],
    ) -> List[str]:
        """面向 TopicReplier 的歌曲事实检索接口。"""
        if not constraints:
            return []

        dedup: List[str] = []
        seen = set()
        for raw in constraints:
            song_name = self._extract_song_name(raw)
            if not song_name:
                continue

            intro = await asyncio.to_thread(get_song_introduction, knowledge_db, song_name)
            lyrics = await asyncio.to_thread(get_song_lyrics, knowledge_db, song_name)

            if intro:
                text = f"《{song_name}》的介绍:\n{intro}"
                if text not in seen:
                    seen.add(text)
                    dedup.append(text)

            if lyrics:
                text = f"《{song_name}》的歌词:\n{lyrics}"
                if text not in seen:
                    seen.add(text)
                    dedup.append(text)

        return dedup

    def _extract_song_name(self, text: str) -> str:
        content = (text or "").strip()
        if not content:
            return ""

        m = re.search(r"《([^》]+)》", content)
        if m:
            return m.group(1).strip()

        if "是一首歌" in content:
            return content.split("是一首歌", 1)[0].strip().strip("《》")

        return content.strip("\"'“”‘’《》")
    
