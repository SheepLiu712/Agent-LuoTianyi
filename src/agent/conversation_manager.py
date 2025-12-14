"""
对话管理模块

管理对话历史、上下文状态和会话记忆
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
from abc import ABC, abstractmethod

from ..utils.logger import get_logger
from ..llm.siliconflow_client import SiliconFlowClient


class ConversationMemory(ABC):
    """对话记忆基类"""

    @abstractmethod
    def add_message(self, role: str, content: str, metadata: Optional[Dict] = None) -> None:
        """添加消息到记忆中"""
        pass

    @abstractmethod
    def get_messages(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """获取消息历史"""
        pass

    @abstractmethod
    def clear(self) -> None:
        """清空记忆"""
        pass


class BufferMemory(ConversationMemory):
    """缓冲区记忆

    保存最近N轮对话的简单记忆实现
    """

    def __init__(self, max_size: int = 10):
        """初始化缓冲区记忆

        Args:
            max_size: 最大保存的对话轮数
        """
        self.max_size = max_size
        self.messages: List[Dict[str, Any]] = []
        self.logger = get_logger(__name__)

    def add_message(self, role: str, content: str, metadata: Optional[Dict] = None) -> None:
        """添加消息到缓冲区

        Args:
            role: 消息角色 (user/assistant)
            content: 消息内容
            metadata: 额外元数据
        """
        # TODO: 实现消息添加逻辑
        # - 创建消息对象
        # - 添加时间戳
        # - 维护缓冲区大小限制
        pass

    def get_messages(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """获取消息历史

        Args:
            limit: 限制返回的消息数量

        Returns:
            消息历史列表
        """
        # TODO: 实现消息获取逻辑
        pass

    def clear(self) -> None:
        """清空缓冲区"""
        # TODO: 清空消息列表
        pass


class SummaryMemory(ConversationMemory):
    """摘要记忆

    对历史对话进行摘要压缩的记忆实现
    """

    def __init__(
        self,
        config: Dict[str, Any]
    ):
        """初始化摘要记忆

        Args:
            config: 配置字典
        """
        self.max_tokens = config.get("max_tokens", 1000)
        self.max_show_round = config.get("max_show_round", 20)
        self.max_store_round = config.get("max_store_round", 40)
        self.round_counter = 0
        self.summary: str = "没有更早的消息"
        self.recent_messages: List[Dict[str, Any]] = []
        self.logger = get_logger(__name__)
        self.summary_llm_config = config.get("summary_llm", None)
        self.summary_llm = self._get_summary_llm(self.summary_llm_config)
        self.summary_prompt = self._get_summary_prompt(config.get("summary_prompt", ""))
        self.logger.info("摘要记忆初始化完成")

    def add_message(self, role: str, content: str, metadata: Optional[Dict] = None) -> None:
        """添加消息并更新摘要

        Args:
            role: 消息角色
            content: 消息内容
            metadata: 额外元数据
        """
        self.recent_messages.append({"role": role, "content": content, "metadata": metadata})
        if len(self.recent_messages) > self.max_store_round:
            self.recent_messages.pop(0)
        self.round_counter += 1
        if self.round_counter % self.max_show_round == 0: # 每次进来一批完全新的，不被主要回答LLM看到的对话
            self._generate_summary()


    def get_messages(self, limit: Optional[int] = None) -> Dict[str, Any]:
        message = {
            "摘要": self.summary,
            "最近消息": self.recent_messages[-limit:] if limit else self.recent_messages[-self.max_show_round:]
        }
        self.logger.debug(f"获取消息：{message}")
        return message

    def clear(self) -> None:
        """清空摘要和消息"""
        self.summary = "没有更早的消息"
        self.recent_messages.clear()

    def _generate_summary(self) -> str:
        """生成对话摘要

        Returns:
            对话摘要文本
        """
        query = self.summary_prompt + f"\n现有总结：{self.summary}\n最近对话：\n{self.recent_messages}"
        self.summary = self.summary_llm.chat(query)
        self.logger.debug(f"生成摘要：{self.summary}")

    def _get_summary_llm(self, summary_llm_config: Dict[str, Any]) -> Optional[SiliconFlowClient]:
        if summary_llm_config is None:
            raise ValueError("summary_llm_config不能为空")
        if summary_llm_config.get("provider") == "siliconflow":
            return SiliconFlowClient(summary_llm_config)
        else:
            raise ValueError(f"不支持的LLM提供商: {summary_llm_config.get('provider')}")
    
    def _get_summary_prompt(self, prompt: str) -> str:
        '''从json模板中获取摘要模板

        Args:
            prompt: prompt模板位置
        
        Return:
            摘要模板
        
        '''
        # 读取json文件
        with open(prompt, 'r', encoding='utf-8') as f:
            import json
            template = json.load(f)
        template = template.get("template", "")
        # self.logger.debug(f"使用摘要模板: {template}")
        return template


class ConversationManager:
    """对话管理器

    管理对话状态、上下文和记忆
    """

    def __init__(self, memory_type: str = "buffer", memory_config: Optional[Dict] = None):
        """初始化对话管理器

        Args:
            memory_type: 记忆类型 (buffer/summary/kg)
            memory_config: 记忆配置参数
        """
        self.logger = get_logger(__name__)
        self.memory = self._create_memory(memory_type, memory_config or {})
        self.context: Dict[str, Any] = {}
        self.session_id: Optional[str] = None
        self.start_time: Optional[datetime] = None

    def _create_memory(self, memory_type: str, config: Dict) -> ConversationMemory:
        """创建记忆实例

        Args:
            memory_type: 记忆类型
            config: 配置参数

        Returns:
            记忆实例
        """
        if memory_type == "buffer":
            raise NotImplementedError("BufferMemory尚未实现")
            return BufferMemory(max_size=config.get("max_size", 10))
        elif memory_type == "summary":
            return SummaryMemory(
                config
            )
        else:
            raise ValueError(f"不支持的记忆类型: {memory_type}")

    def start_session(self, session_id: Optional[str] = None) -> str:
        """开始新的对话会话

        Args:
            session_id: 会话ID，如果为None则自动生成

        Returns:
            会话ID
        """
        # TODO: 实现会话启动逻辑
        # - 生成或设置会话ID
        # - 记录开始时间
        # - 初始化上下文
        pass

    def end_session(self) -> None:
        """结束当前会话"""
        # TODO: 实现会话结束逻辑
        # - 保存会话信息
        # - 清理临时状态
        pass

    def add_user_message(self, content: str, metadata: Optional[Dict] = None) -> None:
        """添加用户消息

        Args:
            content: 消息内容
            metadata: 消息元数据
        """
        # TODO: 添加用户消息到记忆
        self.memory.add_message("user", content, metadata)

    def add_assistant_message(self, content: str, metadata: Optional[Dict] = None) -> None:
        """添加助手消息

        Args:
            content: 消息内容
            metadata: 消息元数据
        """
        # TODO: 添加助手消息到记忆
        self.memory.add_message("Luo Tianyi", content, metadata)

    def get_conversation_history(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """获取对话历史

        Args:
            limit: 限制返回的消息数量

        Returns:
            对话历史
        """
        return self.memory.get_messages(limit)

    def update_context(self, key: str, value: Any) -> None:
        """更新上下文信息

        Args:
            key: 上下文键
            value: 上下文值
        """
        # TODO: 更新上下文字典
        self.context[key] = value

    def get_context(self, key: Optional[str] = None) -> Any:
        """获取上下文信息

        Args:
            key: 上下文键，如果为None则返回整个上下文

        Returns:
            上下文值或整个上下文字典
        """
        # TODO: 返回指定的上下文信息
        if key is None:
            return self.context
        return self.context.get(key)

    def clear_context(self) -> None:
        """清空上下文"""
        # TODO: 清空上下文字典
        self.context.clear()

    def reset(self) -> None:
        """重置对话管理器"""
        # TODO: 重置所有状态
        # - 清空记忆
        # - 清空上下文
        # - 重置会话信息
        self.memory.clear()
        self.clear_context()
        self.session_id = None
        self.start_time = None
        self.logger.info("对话管理器已重置")

    def get_session_info(self) -> Dict[str, Any]:
        """获取会话信息

        Returns:
            会话信息字典
        """
        # TODO: 返回当前会话的详细信息
        return {
            "session_id": self.session_id,
            "start_time": self.start_time,
            "message_count": len(self.memory.get_messages()),
            "context_keys": list(self.context.keys()),
        }
