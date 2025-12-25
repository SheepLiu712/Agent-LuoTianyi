"""
Memory Write Module
-------------------
负责记忆的生成与写入（Generation/Storage）。
核心在于将非结构化的对话流转化为结构化、易于检索的知识片段。
"""

from typing import List, Dict, Any, Optional, Set
from ..utils.logger import get_logger
from .vector_store import VectorStore, Document
from .user_profile import UserProfile
from ..llm.prompt_manager import PromptManager
from ..llm.llm_module import LLMModule
from ..agent.conversation_manager import ConversationItem
import json
import datetime
import time
import os
from collections import deque
from  dataclasses import dataclass, asdict

logger = get_logger("MemoryWriter")

@dataclass
class MemoryUpdateCommand:
    type: str  # e.g., "v_add"
    content: str
    uuid: Optional[str] = None
    def __repr__(self):
        if self.uuid:
            return f"{self.type}(uuid='{self.uuid[:6]}', new_document='{self.content}')"
        else:
            return f"{self.type}(document='{self.content}')" 

class MemoryWriter:
    def __init__(self, config: Dict[str, Any], vector_store: VectorStore, user_profile: UserProfile, prompt_manager: PromptManager):
        self.config = config
        self.vector_store = vector_store
        self.user_profile = user_profile
        self.llm = LLMModule(config["llm_module"], prompt_manager)
        self.recent_update : deque[MemoryUpdateCommand] = deque(maxlen=10)  # 记录最近写入的记忆，防止重复写入
        self.recent_update_path = config.get("recent_update_path", "data/memory/context/recent_update.json")
        os.makedirs(os.path.dirname(self.recent_update_path), exist_ok=True)
        self.load_recent_update()

    def load_recent_update(self):
        if os.path.exists(self.recent_update_path):
            try:
                with open(self.recent_update_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data:
                        self.recent_update.append(MemoryUpdateCommand(**item))
            except Exception as e:
                logger.error(f"Failed to load recent updates: {e}")

    def save_recent_update(self):
        try:
            os.makedirs(os.path.dirname(self.recent_update_path), exist_ok=True)
            with open(self.recent_update_path, "w", encoding="utf-8") as f:
                data = [asdict(cmd) for cmd in self.recent_update]
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f"Failed to save recent updates: {e}")

    def process_interaction(self, user_input: str, history: List[ConversationItem], used_uuid: Set[str]):
        """
        分析最近的交互，提取有价值的信息存入记忆库。
        """
        # 1. 提取关键信息
        update_cmd = self._extract_knowledge(user_input, history, used_uuid)

        # 2. 准备可能被更新的文档的UUID列表
        uuid_can_be_used = used_uuid.copy()
        for update in self.recent_update:
            if update.uuid:
                uuid_can_be_used.add(update.uuid)


        for funcname, kwargs in update_cmd:
            if "add" in funcname.lower():
                content = kwargs.get("document", "")
                self.v_add(content)
            elif "username" in funcname.lower():
                new_name = kwargs.get("new_name", "")
                self.update_username(new_name)
            elif "update" in funcname.lower():
                uuid_short = kwargs.get("uuid", "")
                for uuid in used_uuid:
                    if uuid is None:
                        continue
                    if uuid.startswith(uuid_short):
                        uuid_to_update = uuid
                        break
                else:
                    logger.warning(f"No matching UUID found for short UUID: {uuid_short}")
                    
                content = kwargs.get("new_document", "")
                if content == "":
                    content = kwargs.get("document", "")
                self.v_update(uuid_to_update, content)


    def _extract_knowledge(self, user_input: str, history: List[ConversationItem], used_uuid: Set[str]) -> Dict[str, Any]:
        """
        使用LLM从对话历史中提取有价值的记忆内容。
        Args:
            history: 最近的对话历史
        """
        history_str = [f"{item.source}: {item.content}" for item in history]
        recent_update_str = [str(cmd) for cmd in self.recent_update]
        related_docs = self.vector_store.get_document_by_id(list(used_uuid))
        related_doc_str = [f"ID: {doc.id[:6]}, Content: {doc.content}" for doc in related_docs if doc]
        
        cmd = []
        try:
            response = self.llm.generate_response(user_input=user_input, history=history_str, recent_updates=recent_update_str, related_memories=related_doc_str)
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
                    kwargs[key.strip()] = value.strip().strip("\'").strip('\"')  
                cmd.append((funcname.strip(), kwargs))
        except Exception as e:
            logger.warning(f"Error generating memory update commands: {e}")
        finally:
            return cmd

    def v_add(self, document: str):
        """
        向向量存储中添加新的记忆片段
        """
        doc = Document(content=document, metadata={"source": "memory_writer", "timestamp": time.strftime("%Y-%m-%d")})
        ids = self.vector_store.add_documents([doc])
        self.recent_update.append(MemoryUpdateCommand(type="v_add", content=document, uuid=ids[0] if ids else None))
        self.save_recent_update()

    def v_update(self, uuid: str, new_document: str):
        """
        更新向量存储中的记忆片段
        """
        if uuid is None:
            logger.warning("UUID is required for updating a document.")
            return
        doc = Document(content=new_document, metadata={"source": "memory_writer", "timestamp": time.strftime("%Y-%m-%d")}, id=uuid)
        self.vector_store.update_document(doc_id=uuid, document=doc)
        self.recent_update.append(MemoryUpdateCommand(type="v_update", content=new_document, uuid=uuid))
        self.save_recent_update()

    def update_username(self, new_name: str):
        """
        更新用户名称
        """
        self.user_profile.update_username(new_name)