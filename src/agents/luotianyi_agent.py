"""
洛天依Agent主类

实现洛天依角色扮演对话Agent的核心逻辑
"""

from typing import Dict, List, Optional, Any
from abc import ABC, abstractmethod
import threading
import os

from jinja2 import Template
from datetime import datetime

from ..llm.siliconflow_client import SiliconFlowClient
from ..knowledge.graph_retriever import GraphRetriever
from ..knowledge.vector_store import VectorStoreFactory, VectorStore
from ..llm.prompt_manager import PromptManager
from .conversation_manager import ConversationManager
from ..utils.logger import get_logger


class BaseAgent(ABC):
    """Agent基类"""

    @abstractmethod
    def chat(self, message: str, **kwargs) -> str:
        """处理用户消息并返回回复"""
        pass

    @abstractmethod
    def reset(self) -> None:
        """重置对话状态"""
        pass


class LuoTianyiAgent(BaseAgent):
    """洛天依对话Agent

    基于图结构增强RAG的洛天依角色扮演对话系统
    """

    def __init__(self, config_path: str = "config/config.yaml"):
        """初始化洛天依Agent

        Args:
            config_path: 配置文件路径
        """
        self.logger = get_logger(__name__)
        self.config = self._load_config(config_path)
        self.persona = self._load_persona()

        # 初始化各个组件
        self.llm_client = self._init_llm_client()
        self.vector_store = self._init_vector_store()
        self.graph_retriever = self._init_graph_retriever()
        self.prompt_manager = self._init_prompt_manager()
        self.conversation_manager = self._init_conversation_manager()

        self.logger.info("洛天依Agent初始化完成")

    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """加载配置文件

        Args:
            config_path: 配置文件路径

        Returns:
            配置字典
        """
        if not os.path.exists(config_path):
            self.logger.error(f"配置文件不存在: {config_path}")
            raise FileNotFoundError(f"配置文件不存在: {config_path}")
        with open(config_path, "r", encoding="utf-8") as f:
            try:
                import json

                config = json.load(f)
            except Exception as e:
                self.logger.error(f"加载配置文件失败 {config_path}: {e}")
                raise ValueError(f"配置文件格式错误: {config_path}")
            config = self._apply_env_variables(config)
            self._validate_config_format(config)
            return config

    def _apply_env_variables(self, config: Any, parent_key: str = "") -> Any:
        """递归应用环境变量替换配置中的变量，支持多层嵌套
        Args:
            config: 配置字典或列表或值
            parent_key: 当前递归的父键路径
        Returns:
            替换后的配置
        """
        if isinstance(config, dict):
            for key, value in config.items():
                full_key = f"{parent_key}.{key}" if parent_key else key
                config[key] = self._apply_env_variables(value, full_key)
            return config
        elif isinstance(config, list):
            return [
                self._apply_env_variables(item, f"{parent_key}[{i}]")
                for i, item in enumerate(config)
            ]
        elif isinstance(config, str) and config.startswith("$"):
            env_var = config[1:]
            if env_var.startswith("{") and env_var.endswith("}"):
                env_var = env_var[1:-1]
            env_value = os.environ.get(env_var)
            if env_value is not None:
                self.logger.debug(f"环境变量替换: {parent_key} -> {env_var} = {env_value}")
                return env_value
            else:
                self.logger.warning(f"环境变量未设置: {env_var} (路径: {parent_key})")
                return config
        else:
            return config

    def _validate_config_format(self, config: Dict[str, Any]) -> None:
        """验证配置格式

        Args:
            config: 配置字典

        Raises:
            ValueError: 如果配置格式不正确
        """
        pass

    def _load_persona(self) -> Dict[str, Any]:
        """加载人设配置

        Returns:
            人设配置字典
        """
        persona_file = self.config["agent"].get("persona_file", None)
        if not persona_file or not os.path.exists(persona_file):
            self.logger.error(f"人设文件不存在: {persona_file}")
            raise FileNotFoundError(f"人设文件不存在: {persona_file}")
        with open(persona_file, "r", encoding="utf-8") as f:
            try:
                import json

                persona = json.load(f)
            except Exception as e:
                self.logger.error(f"加载人设文件失败 {persona_file}: {e}")
                raise ValueError(f"人设文件格式错误: {persona_file}")
        return persona

    def _init_llm_client(self) -> SiliconFlowClient:
        """初始化LLM客户端

        Returns:
            LLM客户端实例
        """
        # TODO: 根据配置初始化硅基流动客户端
        llm_config = self.config.get("llm", {})
        if not llm_config:
            self.logger.error("LLM配置缺失，请检查配置文件")
            raise ValueError("LLM配置缺失")
        return SiliconFlowClient(llm_config)

    def _init_vector_store(self) -> VectorStore:
        """初始化向量存储

        Returns:
            向量存储实例
        """
        # TODO: 根据配置初始化向量数据库
        vector_config = self.config.get("knowledge", {}).get("vector_store", {})
        if not vector_config:
            self.logger.error("向量存储配置缺失，请检查配置文件")
            raise ValueError("向量存储配置缺失")
        return VectorStoreFactory.create_vector_store("chroma", vector_config)

    def _init_graph_retriever(self) -> GraphRetriever:
        """初始化图检索器

        Returns:
            图检索器实例
        """
        # TODO: 根据配置初始化图数据库检索
        pass

    def _init_prompt_manager(self) -> PromptManager:
        """初始化Prompt管理器

        Returns:
            Prompt管理器实例
        """
        prompt_config = self.config.get("prompt", {})
        if not prompt_config:
            self.logger.error("Prompt管理器配置缺失，请检查配置文件")
            raise ValueError("Prompt管理器配置缺失")
        return PromptManager(prompt_config)

    def _init_conversation_manager(self) -> ConversationManager:
        """初始化对话管理器

        Returns:
            对话管理器实例
        """
        return ConversationManager(
            memory_type=self.config.get("conversation", {}).get("memory_type", "buffer"),
            memory_config=self.config.get("conversation", {}).get("memory", {}),
        )

    def chat(self, message: str, **kwargs) -> str:
        """处理用户消息并生成洛天依风格的回复

        Args:
            message: 用户输入消息
            **kwargs: 额外参数

        Returns:
            洛天依的回复文本
        """
        try:
            # 等待上一次对话历史更新线程结束（如有）
            if hasattr(self, '_history_thread') and self._history_thread is not None:
                self._history_thread.join()

            # 1. 意图理解和实体识别
            intent_result = self._understand_intent(message)

            # 2. 知识检索
            retrieved_knowledge = self._retrieve_knowledge(message, intent_result)

            # 3. 检索对话历史
            history = self.get_conversation_history(type="short")

            # 4. 生成回复
            response = self._generate_response(message, intent_result, retrieved_knowledge, history)

            # 5. 更新对话历史（异步线程）
            self._history_thread = threading.Thread(target=self._update_conversation_history, args=(message, response))
            self._history_thread.start()

            # response = response.replace("\n", "")
            return response

        except Exception as e:
            self.logger.error(f"对话处理出错: {e}")
            return self._get_error_response()

    def _understand_intent(self, message: str) -> Dict[str, Any]:
        """理解用户意图和识别实体

        Args:
            message: 用户消息

        Returns:
            意图分析结果
        """
        # TODO: 实现意图理解逻辑
        # - 使用NLP工具进行分词和实体识别
        # - 分类用户意图（问候、询问歌曲、日常聊天等）
        # - 提取关键实体信息
        return "chat"

    def _retrieve_knowledge(self, message: str, intent_result: Dict[str, Any]) -> Dict[str, Any]:
        """检索相关知识

        Args:
            message: 用户消息
            intent_result: 意图分析结果

        Returns:
            检索到的知识信息
        """
        # TODO: 实现知识检索逻辑
        # - 根据意图和实体进行向量检索
        # - 使用图结构进行多跳推理
        # - 合并和排序检索结果
        return {
            "long_memory": [""],
            "knowledge": [""],
            "persona": [""],
        }

    def _generate_response(
        self,
        message: str,
        intent_result: Dict[str, Any],
        knowledge: Dict[str, Any],
        history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """生成洛天依风格的回复

        Args:
            message: 用户消息
            intent_result: 意图分析结果
            knowledge: 检索到的知识
            history: 对话历史
        Returns:
            生成的回复文本
        """
        # 示例：读取并填充 daily_chat_prompt.yaml
        persona = self.get_persona(needed_labels=["basic_info", "personality"])
        prompt = self.prompt_manager.build_conversation_prompt(
            message, persona=persona, knowledge=knowledge, conversation_history=history
        )
        response = self.llm_client.chat(prompt)

        # 4. 示例返回 prompt（实际应用应调用LLM生成回复）
        return response

    def _update_conversation_history(self, user_message: str, bot_response: str) -> None:
        """更新对话历史

        Args:
            user_message: 用户消息
            bot_response: 机器人回复
        """
        self.conversation_manager.add_user_message(user_message)
        self.conversation_manager.add_assistant_message(bot_response)

    def _get_error_response(self) -> str:
        """获取错误回复

        Returns:
            错误情况下的默认回复
        """
        # TODO: 根据人设返回合适的错误回复
        return "诶？天依有点不太明白呢～可以再说一遍吗？"

    def reset(self) -> None:
        """重置对话状态"""
        # TODO: 实现状态重置
        # - 清空对话历史
        # - 重置上下文状态
        self.logger.info("对话状态已重置")

    def get_conversation_history(self, type: str = "short") -> List[Dict[str, str]]:
        """获取对话历史

        Args:
            type: 历史类型，支持"short"和"full"

        Returns:
            对话历史列表
        """
        # TODO: 返回对话历史
        return self.conversation_manager.get_conversation_history()

    def update_persona(self, persona_updates: Dict[str, Any]) -> None:
        """更新人设配置

        Args:
            persona_updates: 人设更新内容
        """
        # TODO: 实现人设动态更新
        pass

    def get_persona(self, needed_labels: List[str]) -> Dict[str, Any]:
        """获取人设信息

        Args:
            needed_labels: 需要的人设标签

        Returns:
            人设信息字典
        """
        return {label: self.persona.get(label) for label in needed_labels}
