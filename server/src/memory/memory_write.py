"""
Memory Write Module
-------------------
负责记忆的生成与写入（Generation/Storage）。
核心在于将非结构化的对话流转化为结构化、易于检索的知识片段。
"""

from typing import List, Dict, Any, Optional, Set
from ..utils.logger import get_logger
from ..database.vector_store import VectorStore, Document
from ..llm.prompt_manager import PromptManager
from ..llm.llm_module import LLMModule
import time
import os
import asyncio
from dataclasses import dataclass, asdict
from sqlalchemy.orm import Session
from redis import Redis
from ..database import User
from ..database.database_service import get_used_memory_uuid, get_recent_memory_update_from_buffer, update_user_nickname, write_memory_update

from ..types.memory_type import MemoryUpdateCommand


logger = get_logger("MemoryWriter")


class MemoryWriter:
    def __init__(self, config: Dict[str, Any], prompt_manager: PromptManager):
        self.config = config
        self.llm = LLMModule(config["llm_module"], prompt_manager)

    async def process_interaction(
        self,
        db: Session,
        redis: Redis,
        vector_store: VectorStore,
        user_id: str,
        user_input: str,
        agent_response_content: List[str],
        history: str,
        commit: bool = True
    ):
        """
        分析最近的交互，提取有价值的信息存入记忆库。
        """
        used_uuid_task = asyncio.to_thread(get_used_memory_uuid, db, redis, user_id)
        recent_update_task = asyncio.to_thread(get_recent_memory_update_from_buffer, db, redis, user_id)
        used_uuid, recent_update = await asyncio.gather(used_uuid_task, recent_update_task)
        update_cmd = await self._extract_knowledge(
            vector_store, user_id, user_input, agent_response_content, history, used_uuid, recent_update
        )

        # 2. 准备可能被更新的文档的UUID列表
        uuid_can_be_used = used_uuid.copy()
        for update in recent_update:
            if update.uuid:
                uuid_can_be_used.append(update.uuid)

        # 3. 执行更新命令
        for funcname, kwargs in update_cmd:
            if "add" in funcname.lower():
                content = kwargs.get("document", "")
                await self.v_add(db, redis, vector_store, recent_update, user_id, content, commit=commit)

            elif "username" in funcname.lower():
                new_name = kwargs.get("new_name", "")
                await asyncio.to_thread(update_user_nickname, db, redis, user_id, new_name, commit=commit)

            elif "update" in funcname.lower():
                uuid_short = kwargs.get("uuid", "")
                for uuid in uuid_can_be_used:
                    if uuid is None:
                        continue
                    if uuid.startswith(uuid_short):
                        uuid_to_update = uuid
                        break
                else:
                    uuid_to_update = None
                    logger.warning(f"No matching UUID found for short UUID: {uuid_short}")

                content = kwargs.get("new_document", "")
                if content == "":
                    content = kwargs.get("document", "")
                await self.v_update(db, redis,  vector_store, recent_update, user_id, uuid_to_update, content, commit=commit)

    async def _extract_knowledge(
        self,
        vector_store: VectorStore,
        user_id: str,
        user_input: str,
        agent_response_content: List[str],
        history: str,
        used_uuid: List[str],
        recent_update: List[MemoryUpdateCommand],
    ) -> Dict[str, Any]:
        """
        使用LLM从对话历史中提取有价值的记忆内容。
        Args:
            history: 最近的对话历史
        """
        history_str = history
        recent_update_str = [str(cmd) for cmd in recent_update]
        related_docs = vector_store.get_document_by_id(list(used_uuid))
        related_doc_str = [f"ID: {doc.id[:6]}, Content: {doc.content}" for doc in related_docs if doc]

        cmd = []
        try:
            response = await self.llm.generate_response(
                user_input=user_input,
                agent_response=agent_response_content,
                history=history_str,
                recent_updates=recent_update_str,
                related_memories=related_doc_str,
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
                    key, value = arg.split("=", 1)
                    kwargs[key.strip()] = value.strip().strip("'").strip('"')
                cmd.append((funcname.strip(), kwargs))
        except Exception as e:
            logger.warning(f"Error generating memory update commands: {e}")
        finally:
            return cmd

    async def v_add(self, db: Session, redis: Redis, vector_store: VectorStore, recent_update: List[MemoryUpdateCommand], user_id: str, document: str, commit: bool = True):
        """
        向向量存储中添加新的记忆片段
        """
        doc = Document(content=document, metadata={"source": "memory_writer", "timestamp": time.strftime("%Y-%m-%d"), "user_id": user_id})
        ids = await asyncio.to_thread(vector_store.add_documents, [doc])
        # logger.debug(f"Successfully added document with UUIDs: {ids} for user {user_id}")
        update_cmd = MemoryUpdateCommand(type="v_add", content=document, uuid=ids[0] if ids else None)
        recent_update.append(update_cmd)
        await asyncio.to_thread(write_memory_update, db, redis, user_id, update_cmd, commit=commit)


    async def v_update(self, db: Session, redis: Redis, vector_store: VectorStore, recent_update: List[MemoryUpdateCommand], user_id: str, uuid: str, new_document: str, commit: bool = True):
        """
        更新向量存储中的记忆片段
        """
        if uuid is None:
            logger.warning("UUID is required for updating a document.")
            return
        doc = Document(
            content=new_document, metadata={"source": "memory_writer", "timestamp": time.strftime("%Y-%m-%d"), "user_id": user_id}, id=uuid
        )
        ret = await asyncio.to_thread(vector_store.update_document, doc_id=uuid, document=doc)
        if ret:
            logger.debug(f"Successfully updated document with UUID: {uuid} for user {user_id}")
            update_cmd = MemoryUpdateCommand(type="v_update", content=new_document, uuid=uuid)
            recent_update.append(update_cmd)
            await asyncio.to_thread(write_memory_update, db, redis, user_id, update_cmd, commit=commit)
        else:
            logger.warning(f"Failed to update document with UUID: {uuid} for user {user_id}")