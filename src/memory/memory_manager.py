"""
Memory Manager Module
---------------------
负责协调记忆的生成（写入）和检索（读取）。
作为整个记忆系统的统一入口，对外提供 process_user_input (读取) and post_process_interaction (写入) 接口。
"""

from typing import List, Dict, Any, Optional
from ..utils.logger import get_logger
from .memory_search import MemorySearcher
from .memory_write import MemoryWriter
from .vector_store import VectorStoreFactory, VectorStore
from .graph_retriever import GraphRetrieverFactory, GraphRetriever
from ..llm.llm_module import LLMModule
from ..llm.prompt_manager import PromptManager
from ..agent.conversation_manager import ConversationItem
from threading import Thread


class MemoryManager:
    def __init__(
        self,
        config: Dict[str, Any],
        prompt_manager: PromptManager,
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
        self.vector_store: VectorStore = VectorStoreFactory.create_vector_store(config["vector_store"]["store_type"],config["vector_store"])
        self.memory_searcher = MemorySearcher(config["memory_searcher"], self.vector_store, self.graph_retriever, prompt_manager)
        self.memory_writer = MemoryWriter(config["memory_writer"], self.vector_store, prompt_manager)
        self.post_process_thread: Optional[Thread] = None

    def get_knowledge(self, user_input: str, history: List[ConversationItem]) -> List[str]:
        """
        根据用户输入检索相关记忆

        Args:
            user_input: 用户的输入文本

        Returns:
            包含检索到的记忆信息的字典
        """
        if self.post_process_thread and self.post_process_thread.is_alive():
            self.logger.info("Waiting for previous memory write to complete...")
            self.post_process_thread.join()
        history_texts = [item.__repr__() for item in history]
        return self.memory_searcher.search(user_input, history_texts)
    
    def post_process_interaction(self, history: List[ConversationItem], used_uuid: Optional[set] = None):
        """
        根据最新的交互内容，生成并写入新的记忆

        Args:
            history: 包含最近交互内容的列表
            used_uuid: 在检索过程中使用过的记忆UUID集合
        """
        self.post_process_thread = Thread(target=self.memory_writer.process_interaction, args=(history, used_uuid or set()))
        self.post_process_thread.daemon = True
        self.post_process_thread.start()