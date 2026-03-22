"""
Memory Write Module
-------------------
负责记忆的生成与写入（Generation/Storage）。
核心在于将非结构化的对话流转化为结构化、易于检索的知识片段。
"""

from typing import List, Dict, Any
from ..utils.logger import get_logger
from ..database.vector_store import VectorStore, Document
from ..utils.llm.prompt_manager import PromptManager
from ..utils.llm.llm_module import LLMModule
import time
import asyncio
from sqlalchemy.orm import Session
from ..database.memory_storage import MemoryStorage
from ..database.database_service import update_user_nickname, write_memory_update

from ..types.memory_type import MemoryUpdateCommand


logger = get_logger("MemoryWriter")


class MemoryWriter:
    def __init__(self, config: Dict[str, Any], prompt_manager: PromptManager):
        self.config = config
        self.llm = LLMModule(config["llm_module"], prompt_manager)

    async def process_interaction(
        self,
        db: Session,
        redis: MemoryStorage,
        vector_store: VectorStore,
        user_id: str,
        user_input: str,
        agent_response_content: List[str],
        history: str,
        current_dialogue: str = "",
        related_memories: List[str] | None = None,
        commit: bool = True
    ):
        """
        分析最近的交互，提取有价值的信息存入记忆库。
        """
        update_cmd = await self._extract_knowledge(
            user_input,
            agent_response_content,
            history,
            current_dialogue=current_dialogue,
            related_memories=related_memories or [],
        )

        # 执行更新命令
        for funcname, kwargs in update_cmd:
            lowered = funcname.lower()
            if lowered == "write_user_memory":
                content = kwargs.get("content", "")
                await self.write_user_memory(db, redis, vector_store, user_id, content, commit=commit)

            elif lowered == "write_event_memory":
                content = kwargs.get("content", "")
                await self.write_event_memory(db, redis, vector_store, user_id, content, commit=commit)

            elif "username" in lowered:
                new_name = kwargs.get("new_name", "")
                await asyncio.to_thread(update_user_nickname, db, redis, user_id, new_name, commit=commit)

            elif lowered == "v_add":
                # 兼容旧 prompt 的命令，默认按 user_memory 处理。
                content = kwargs.get("document", "")
                await self.write_user_memory(db, redis, vector_store, user_id, content, commit=commit)

    async def _extract_knowledge(
        self,
        user_input: str,
        agent_response_content: List[str],
        history: str,
        current_dialogue: str,
        related_memories: List[str],
    ) -> Dict[str, Any]:
        """
        使用LLM从对话历史中提取有价值的记忆内容。
        Args:
            history: 最近的对话历史
        """
        history_str = history

        cmd = []
        try:
            response = await self.llm.generate_response(
                user_input=user_input,
                agent_response=agent_response_content,
                history=history_str,
                current_dialogue=current_dialogue,
                related_memories=related_memories,
            )
            response = response.split("\n")
            logger.debug(f"Memory extraction response: {response}")
            for line in response:
                if line.startswith("##"):
                    break
                if line == "":
                    continue
                if not "(" in line or ")" not in line:
                    logger.warning(f"Unrecognized command format: {line}")
                    continue
                funcname, args_str = line.split("(", 1)
                args_str = args_str.rstrip(")")
                kwargs = {}
                for arg in args_str.split(","):
                    if "=" not in arg:
                        continue
                    key, value = arg.split("=", 1)
                    kwargs[key.strip()] = value.strip().strip("'").strip('"')
                cmd.append((funcname.strip(), kwargs))
        except Exception as e:
            logger.warning(f"Error generating memory update commands: {e}")
        finally:
            return cmd

    async def write_user_memory(
        self,
        db: Session,
        redis: MemoryStorage,
        vector_store: VectorStore,
        user_id: str,
        content: str,
        commit: bool = True,
    ) -> bool:
        """写入用户长期记忆：若存在相似记忆则跳过。"""
        text = (content or "").strip()
        if not text:
            return False

        threshold = float(self.config.get("user_memory_dedup_threshold", 0.82))
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
        await asyncio.to_thread(write_memory_update, db, redis, user_id, update_cmd, commit=commit)
        return True

    async def write_event_memory(
        self,
        db: Session,
        redis: MemoryStorage,
        vector_store: VectorStore,
        user_id: str,
        content: str,
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
        await asyncio.to_thread(write_memory_update, db, redis, user_id, update_cmd, commit=commit)
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

    def _normalize_text(self, text: str) -> str:
        return " ".join((text or "").strip().split())