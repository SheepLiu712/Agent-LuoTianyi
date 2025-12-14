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
from ..gui.binder import AgentBinder
from ..utils.logger import get_logger
from ..utils.helpers import load_config
from ..tts import TTSModule
from ..gui import MainWindow


class LuoTianyiAgent:
    """洛天依Agent类

    实现洛天依角色扮演对话Agent的核心逻辑
    """

    def __init__(self, config_path: str = "config/test_config.json") -> None:
        """初始化洛天依Agent

        Args:
            config_path: 配置文件路径
        """
        self.config = load_config(config_path)
        self.logger = get_logger("LuoTianyiAgent")

        # 各种模块初始化
        self.ui_binder = AgentBinder(self.handle_user_input)  # UI绑定器
        self.prompt_manager = PromptManager(self.config.get("prompt_manager", {}))  # 提示管理器
        self.conversation_manager = None  # TODO: 对话管理器
        self.memory_manager = None  # TODO: 记忆管理器

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

        responses = self.main_chat.generate_response(user_input)


        task_list: List[tuple[str, OneSentenceChat]] = []
        for idx,resp in enumerate(responses):
            print(resp)
            task_id = self.tts_engine.add_task(resp.content, resp.tone,idx)
            task_list.append((task_id, resp))

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
            self.tts_engine.play_audio(output_path)


