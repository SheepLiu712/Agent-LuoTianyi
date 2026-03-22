"""
Memory Manager Module
---------------------
负责协调记忆的生成（写入）和检索（读取）。
作为整个记忆系统的统一入口，对外提供 process_user_input (读取) and post_process_interaction (写入) 接口。
"""

from typing import List, Dict, Any
import asyncio
from sqlalchemy.orm import Session
from ..database.memory_storage import MemoryStorage

from ..utils.logger import get_logger
from .memory_search import MemorySearcher
from .memory_write import MemoryWriter
from .user_profile_updater import UserProfileUpdater
from ..music.singing_manager import SingingManager
from .graph_retriever import GraphRetrieverFactory, GraphRetriever
from ..utils.llm.prompt_manager import PromptManager
from ..database import VectorStore, KnowledgeGraph
from ..database.database_service import get_user_nickname, get_user_description, update_user_description

class MemoryManager:
    def __init__(
        self,
        config: Dict[str, Any],
        prompt_manager: PromptManager,
        singing_manager: SingingManager,
    ):
        """
        初始化记忆管理器

        Args:
            llm: 用于生成和检索推理的大模型接口
            vector_store: 用于存储非结构化文本记忆（如对话历史摘要）
            knowledge_graph: 用于存储结构化知识（如VCPedia数据）
        """
        self.logger = get_logger(__name__)
        self.config = config
        self.graph_retriever: GraphRetriever = GraphRetrieverFactory.create_retriever(
            config["graph_retriever"]["retriever_type"], config["graph_retriever"]
        )
        self.memory_searcher = MemorySearcher(config["memory_searcher"], prompt_manager, singing_manager)
        self.memory_writer = MemoryWriter(config["memory_writer"], prompt_manager)
        self.user_profile_updater = UserProfileUpdater(config["user_profile"], prompt_manager)

    async def get_knowledge(
        self,
        db: Session,
        redis: MemoryStorage,
        vector_store: VectorStore,
        knowledge_db: Session,
        user_id: str,
        user_input: str,
        history: str,
    ) -> List[str]:
        """
        根据用户输入检索相关记忆

        Args:
            user_input: 用户的输入文本

        Returns:
            包含检索到的记忆信息的字典
        """
        return await self.memory_searcher.search(
            db,
            redis,
            vector_store,
            knowledge_db,
            user_id,
            user_input,
            history,
        )

    async def post_process_interaction(
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
        根据最新的交互内容，生成并写入新的记忆

        Args:
            user_input: 用户的输入文本
            history: 包含最近交互内容的列表
        """
        await self.memory_writer.process_interaction(
            db,
            redis,
            vector_store,
            user_id,
            user_input,
            agent_response_content,
            history,
            current_dialogue=current_dialogue,
            related_memories=related_memories or [],
            commit=commit
        )

    async def write_user_memory(
        self,
        db: Session,
        redis: MemoryStorage,
        vector_store: VectorStore,
        user_id: str,
        content: str,
        commit: bool = True,
    ) -> bool:
        return await self.memory_writer.write_user_memory(
            db=db,
            redis=redis,
            vector_store=vector_store,
            user_id=user_id,
            content=content,
            commit=commit,
        )

    async def write_event_memory(
        self,
        db: Session,
        redis: MemoryStorage,
        vector_store: VectorStore,
        user_id: str,
        content: str,
        commit: bool = True,
    ) -> bool:
        return await self.memory_writer.write_event_memory(
            db=db,
            redis=redis,
            vector_store=vector_store,
            user_id=user_id,
            content=content,
            commit=commit,
        )

    async def get_username(self,  db: Session, redis: MemoryStorage, user_id: str) -> str:
        """
        获取用户的名称
        """
        return await asyncio.to_thread(get_user_nickname, db, redis, user_id)

    async def update_user_profile_by_topic(
        self,
        db: Session,
        redis: MemoryStorage,
        user_id: str,
        history: str,
        current_dialogue: str,
        commit: bool = True,
    ) -> str:
        """
        基于单个话题涉及对话，判断并更新用户画像。

        Returns:
            更新后的画像文本；如果不需要更新则返回空字符串。
        """
        current_profile = await asyncio.to_thread(get_user_description, db, redis, user_id) or ""
        new_profile = await self.user_profile_updater.update_profile(
            history=history,
            current_dialogue=current_dialogue,
            current_profile=current_profile,
        )
        if not new_profile:
            return ""

        await asyncio.to_thread(
            update_user_description,
            db,
            redis,
            user_id,
            new_profile,
            commit,
        )
        return new_profile
