"""
洛天依Agent主类

实现洛天依角色扮演对话Agent的核心逻辑
"""

from typing import Dict, List, Optional, Any
from abc import ABC, abstractmethod
import threading
import os
import time

from ..llm.prompt_manager import PromptManager
from .main_chat import MainChat, OneSentenceChat
from .conversation_manager import ConversationManager
from ..gui.binder import AgentBinder
from ..utils.logger import get_logger
from ..utils.helpers import load_config
from ..tts import TTSModule
from ..gui import MainWindow
from ..utils.enum_type import ContextType, ConversationSource
from ..memory.memory_manager import MemoryManager


class LuoTianyiAgent:
    """洛天依Agent类

    实现洛天依角色扮演对话Agent的核心逻辑
    """

    def __init__(self, config_path: str = "config/config.json") -> None:
        """初始化洛天依Agent

        Args:
            config_path: 配置文件路径
        """
        self.config = load_config(config_path)
        self.logger = get_logger("LuoTianyiAgent")
        self.prompt_manager = PromptManager(self.config.get("prompt_manager", {}))  # 提示管理器

        # 各种模块初始化
        self.conversation_manager = ConversationManager(self.config.get("conversation_manager", {}), self.prompt_manager)  # 对话管理器
        self.ui_binder = AgentBinder(
            hear_callback=self.handle_user_input,
            history_callback=self.handle_history_request
        )  # UI绑定器

        memory_config = self.config.get("memory_manager", {})
        # Inject crawler config into memory_searcher config for VCPediaFetcher
        if "memory_searcher" in memory_config:
            memory_config["memory_searcher"]["crawler"] = self.config.get("crawler", {})
            
        self.memory_manager = MemoryManager(memory_config, self.prompt_manager)  # 记忆管理器

        self.tts_engine = TTSModule(self.config.get("tts", {}))
        self.window = MainWindow(self.config["gui"], self.config["live2d"], self.ui_binder)

        self.main_chat = MainChat(
            self.config["main_chat"],
            self.prompt_manager,
            available_tone=self.tts_engine.get_available_tones(),
            available_expression=self.ui_binder.model.get_available_expressions(),
        )

    def handle_user_input(self, user_input: str) -> str:
        """处理用户输入并生成响应

        Args:
            user_input: 用户输入文本

        Returns:
            生成的响应文本
        """
        self.ui_binder.start_thinking()

        conversation_history = self.conversation_manager.get_context()
        # 记忆检索
        username = self.memory_manager.get_username()
        retrieved_knowledge = self.memory_manager.get_knowledge(user_input, conversation_history)
        self.conversation_manager.add_conversation(ConversationSource.USER, user_input, type=ContextType.TEXT)
        responses = self.main_chat.generate_response(user_input, conversation_history, retrieved_knowledge, username=username)

        # 逐条处理响应，创建tts任务，并添加对话
        task_list: List[tuple[str, OneSentenceChat]] = []
        for idx,resp in enumerate(responses):
            self.conversation_manager.add_conversation(ConversationSource.AGENT, resp.content, type=ContextType.TEXT)
            task_id = self.tts_engine.add_task(resp.content, resp.tone,idx)
            task_list.append((task_id, resp))
        
        # 记忆写入（异步）
        agent_response_contents = [resp.content for resp in responses]
        self.memory_manager.post_process_interaction(user_input, agent_response_contents, conversation_history)

        # 等待所有TTS任务完成
        for task_id, resp in task_list:
            while True:
                output_path = self.tts_engine.get_task_result(task_id)
                if output_path:
                    break
                time.sleep(0.01)

            # 更新UI
            self.ui_binder.stop_thinking()
            self.ui_binder.model.set_expression_by_cmd(resp.expression)
            self.ui_binder.response_signal.emit(resp.content)

            # 播放语音
            self.ui_binder.start_mouth_move(wav_path=output_path)
            self.tts_engine.play_audio(output_path)

    def handle_history_request(self, count: int, end_index: int):
        """处理历史记录请求
        
        Args:
            count: 请求的数量
            end_index: 结束索引（不包含），-1表示从最新开始
            
        Returns:
            (history_list, start_index)
        """
        total_count = self.conversation_manager.index_data["total_count"]
        
        if end_index == -1 or end_index > total_count:
            end_index = total_count
            
        start_index = max(0, end_index - count)
        
        # 如果请求范围无效（例如已经到了最开始），返回空列表
        if start_index >= end_index:
            return [], 0
            
        history_items = self.conversation_manager.get_history(start_index, end_index)
        
        # 转换为UI需要的格式
        result = []
        for item in history_items:
            result.append({
                "content": item.content,
                "source": item.source,
                "timestamp": item.timestamp
            })
            
        return result, start_index


