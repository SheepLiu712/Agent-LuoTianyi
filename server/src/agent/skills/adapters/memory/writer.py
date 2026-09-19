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

from src.subconscious.memory.intentional_memory_commit import (
    IntentionalMemoryCommitMixin,
)
from src.subconscious.memory.memory_legacy_write import LegacyMemoryWriteMixin
from src.system.database.vector_store import VectorStore
from src.utils.llm.llm_module import LLMModule
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.system.database.services.memory_store import MemoryStore


logger = get_logger("MemoryWriter")


class MemoryWriter(IntentionalMemoryCommitMixin, LegacyMemoryWriteMixin):
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
                vector_store, user_id, user_items,
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
