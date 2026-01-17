"""
洛天依Agent主类

实现洛天依角色扮演对话Agent的核心逻辑
"""

from typing import Dict, List, Optional, Any, Tuple
from abc import ABC, abstractmethod
import threading
import os
import time

from ..gui.binder import AgentBinder
from ..utils.logger import get_logger
from ..utils.helpers import load_config
from ..gui import MainWindow



class MediaPlayer:
    """
    用来根据输入的音频和表情指令，播放对应的音频文件，并控制Live2D模型的表情变化
    尝试复用现有的所有模块，但是不能通过文本交互
    """

    def __init__(self, config_path: str = "config/config.json") -> None:
        """初始化洛天依Agent

        Args:
            config_path: 配置文件路径
        """
        self.config = load_config(config_path)
        self.logger = get_logger("MediaPlayer")
        self.ui_binder = AgentBinder(
            hear_callback=self.handle_user_input,
            history_callback=self.handle_history_request
        )  # UI绑定器

        self.window = MainWindow(self.config["gui"], self.config["live2d"], self.ui_binder)


    def handle_user_input(self, user_input: str) -> str:
        return


    def handle_history_request(self, count: int, end_index: int):
        return [], 0

    def set_init_expression(self, expression: str):
        """设置Live2D模型的初始表情

        Args:
            expression: 表情指令
        """
        self.ui_binder.model.set_expression_by_cmd(expression)

    def start_play_media(self, media_list: List[Tuple[str, str]]):
        """根据输入的音频和表情指令，播放对应的音频文件，并控制Live2D模型的表情变化

        Args:
            media_list: 包含音频文件路径和表情指令的列表
        """
        def _start_play_media(media_list: List[Tuple[str, str]]):
            time.sleep(3)  # 等待窗口完全显示
            for audio_path, expression in media_list:
                # 控制Live2D模型表情
                self.ui_binder.model.set_expression_by_cmd(expression)
                self.ui_binder.start_mouth_move(wav_path=audio_path)
                self.play_audio(audio_path)
        
        threading.Thread(target=_start_play_media, args=(media_list,)).start()


    def play_audio(self, audio_path: str) -> None:
        """播放音频文件"""
        import sys
        if sys.platform == "win32":
            import winsound
            try:
                winsound.PlaySound(audio_path, winsound.SND_FILENAME)
            except Exception as e:
                self.logger.error(f"Failed to play audio: {e}")
        else:
            self.logger.warning("Auto-play not supported on this platform.")