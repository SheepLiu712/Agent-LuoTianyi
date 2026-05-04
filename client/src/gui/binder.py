import threading
from PySide6.QtCore import QObject, Signal
from ..live2d import Live2dModel
from ..utils.logger import get_logger
from typing import Callable, Tuple, TYPE_CHECKING, Dict

if TYPE_CHECKING:
    from .chat_bubble import ChatBubble


class AgentBinder(QObject):
    response_signal = Signal(str, str)  # uuid, text
    update_signal = Signal(str, str)
    delete_signal = Signal()
    free_signal = Signal(bool)
    history_signal = Signal(list, int)  # history_list, current_top_index
    agent_thinking_signal = Signal(bool) # 是否正在思考中
    local_tts_state_signal = Signal(str, str) # event, conv_uuid

    def __init__(
        self,
        send_text_callback: Callable[[str], str],
        send_image_callback: Callable[[str], str],
        send_typing_callback: Callable[[], None],
        play_local_tts_callback: Callable[[str], bool],
        stop_local_tts_callback: Callable[[], bool],
        set_volume_callback: Callable[[int], None],
        fetch_history_callback: Callable[[int, int], tuple],
        set_model_callback: Callable[[Live2dModel], None],
        auto_login_callback: Callable[[str, str], bool],
        login_callback: Callable[[str, str, bool], Tuple[bool, str]],
        register_callback: Callable[[str, str, str], Tuple[bool, str]],
    ):
        super().__init__()
        self.logger = get_logger(self.__class__.__name__)

        self.send_text_callback = send_text_callback
        self.send_image_callback = send_image_callback
        self.send_typing_callback = send_typing_callback
        self.play_local_tts_callback = play_local_tts_callback
        self.stop_local_tts_callback = stop_local_tts_callback
        self.set_volume_callback = set_volume_callback
        self.fetch_history_callback = fetch_history_callback
        self.set_model_callback = set_model_callback
        self.auto_login_callback = auto_login_callback
        self.login_callback = login_callback
        self.register_callback = register_callback

        self.msg_to_bubble: Dict[str, ChatBubble] = {}  # 用于记录消息ID和气泡的对应关系，以便后续更新气泡内容
        # 将跨线程的更新请求通过 Qt 信号转发到主线程执行
        self.update_signal.connect(self._handle_update_signal)

    def emit_response_signal(self, uuid: str, text: str):
        # 让QT框架外的成员能触发信号
        self.response_signal.emit(uuid, text)

    def emit_update_signal(self, msg_id: str, text: str):
        '''
        根据发来的消息ID和状态，更新对应气泡的状态，具体而言是在气泡旁边显示一个状态图标。
        '''
        # Emit a Qt signal so the actual widget operations run in the UI thread.
        self.update_signal.emit(msg_id, text)

    def _handle_update_signal(self, msg_id: str, text: str):
        # This runs in the QObject's thread (UI thread). Perform the actual widget updates here.
        if msg_id not in self.msg_to_bubble:
            return
        bubble = self.msg_to_bubble[msg_id]
        if text == "failed":
            bubble.set_status(text)
            self.msg_to_bubble.pop(msg_id, None)  # 确认失败后移除映射关系
            return
        elif text == "waiting":
            bubble.set_status("waiting")
            return
        elif text == "submitted":
            bubble.set_status(text)
            self.msg_to_bubble.pop(msg_id, None)  # 提交成功后移除映射关系
            return
        elif text == "has_audio":
            # 当后端保存了本地音频文件，通知气泡添加播放图标
            try:
                if hasattr(bubble, 'add_audio_label'):
                    bubble.add_audio_label()
                else:
                    bubble.set_play_icon()
            except Exception:
                pass
            finally:
                self.msg_to_bubble.pop(msg_id, None)  # 无论成功与否都移除映射关系，避免内存泄漏
        
    def emit_agent_thinking_signal(self, state: str):
        is_thinking = (state == "thinking")
        self.agent_thinking_signal.emit(is_thinking)

    def emit_local_tts_state_signal(self, event: str, conv_uuid: str):
        self.local_tts_state_signal.emit(event, conv_uuid)

    def on_auto_login(self, username: str, token: str) -> bool:
        if self.auto_login_callback:
            return self.auto_login_callback(username, token)
        self.logger.error("Auto login callback not set")
        return False

    def on_login(self, username: str, password: str, do_auto_login: bool = False) -> Tuple[bool, str]:
        if self.login_callback:
            return self.login_callback(username, password, do_auto_login)
        self.logger.error("Login callback not set")
        return False, "Login callback not set"

    def on_register(self, username: str, password: str, invite_code: str) -> Tuple[bool, str]:
        if self.register_callback:
            return self.register_callback(username, password, invite_code)
        self.logger.error("Register callback not set")
        return False, "Register callback not set"

    def on_set_model(self, model: Live2dModel):
        self.set_model_callback(model)

    def on_send_text(self, text: str, bubble):
        """
        接收用户输入的文本，并在后台处理
        """
        msg_id = self.send_text_callback(text)
        self.msg_to_bubble[msg_id] = bubble

    def on_send_image(self, image_path: str, bubble):
        msg_id = self.send_image_callback(image_path)
        self.msg_to_bubble[msg_id] = bubble

    def on_send_typing(self, text_length: int):
        self.send_typing_callback(text_length=text_length)

    def on_play_local_tts(self, conv_uuid: str) -> bool:
        if self.play_local_tts_callback:
            return self.play_local_tts_callback(conv_uuid)
        return False

    def on_stop_local_tts(self) -> bool:
        if self.stop_local_tts_callback:
            return self.stop_local_tts_callback()
        return False

    def on_set_volume(self, percent: int):
        if self.set_volume_callback:
            self.set_volume_callback(percent)


    def on_load_history(self, count: int, end_index: int = -1):
        """
        请求加载历史记录
        :param count: 加载的数量
        :param end_index: 结束索引（不包含），-1表示从最新开始
        """
        if self.fetch_history_callback:
            thread = threading.Thread(target=self._fetch_history, args=(count, end_index))
            thread.daemon = True
            thread.start()
    
    def send_text_proactive(self, text: str) -> str:
        """
        程序化地发送文本消息（用于主动提醒等场景）
        不需要 UI 气泡，只发送消息并让 AI 响应
        :param text: 要发送的文本
        :return: 消息 ID
        """
        if self.send_text_callback:
            msg_id = self.send_text_callback(text)
            # 不添加到 msg_to_bubble，因为这是程序化发送的消息
            return msg_id
        return None

    def _scheduled_start_thinking(self):
        """Legacy hook kept for compatibility; thinking bubble is no longer auto-driven."""
        return

    def load_history(self, count: int, end_index: int = -1):
        self.on_load_history(count, end_index)

    def _fetch_history(self, count, end_index):
        if self.fetch_history_callback:
            history_data, start_index = self.fetch_history_callback(count, end_index)
            self.history_signal.emit(history_data, start_index)