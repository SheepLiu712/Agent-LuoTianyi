"""
Memory Manager Module
---------------------
负责协调记忆的生成（写入）和检索（读取）。
作为整个记忆系统的统一入口，对外提供 process_user_input (读取) and post_process_interaction (写入) 接口。
"""

from typing import List, Dict, Any
import asyncio
from sqlalchemy.orm import Session
from redis import Redis

from ..utils.logger import get_logger
from .memory_search import MemorySearcher
from .memory_write import MemoryWriter
from ..music.singing_manager import SingingManager
from .graph_retriever import GraphRetrieverFactory, GraphRetriever
from ..llm.prompt_manager import PromptManager
from ..database import VectorStore, KnowledgeGraph
from ..database.database_service import get_user_nickname

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

    async def get_knowledge(
        self,
        db: Session,
        redis: Redis,
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
        redis: Redis,
        vector_store: VectorStore,
        user_id: str,
        user_input: str,
        agent_response_content: List[str],
        history: str,
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
            commit=commit
        )

    async def get_username(self,  db: Session, redis: Redis, user_id: str) -> str:
        """
        获取用户的名称
        """
        return await asyncio.to_thread(get_user_nickname, db, redis, user_id)
