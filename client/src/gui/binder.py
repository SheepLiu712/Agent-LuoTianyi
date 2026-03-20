import threading
from PySide6.QtCore import QObject, Signal
from ..live2d import Live2dModel
from ..utils.logger import get_logger
from typing import Callable, Tuple

class AgentBinder(QObject):
    response_signal = Signal(str)
    update_signal = Signal(str, str)
    delete_signal = Signal()
    free_signal = Signal(bool)
    history_signal = Signal(list, int)  # history_list, current_top_index

    def __init__(
        self,
        send_text_callback: Callable[[str], dict],
        send_image_callback: Callable[[str], dict],
        send_typing_callback: Callable[[], dict],
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
        self.fetch_history_callback = fetch_history_callback
        self.set_model_callback = set_model_callback
        self.auto_login_callback = auto_login_callback
        self.login_callback = login_callback
        self.register_callback = register_callback

    def emit_response_signal(self, text: str):
        # 让QT框架外的成员能触发信号
        self.response_signal.emit(text)

    def emit_update_signal(self, request_id: str, text: str):
        self.update_signal.emit(request_id, text)

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

    def on_send_text(self, text: str):
        """
        接收用户输入的文本，并在后台处理
        """
        self.send_text_callback(text)

    def on_send_image(self, image_path: str):
        self.send_image_callback(image_path)

    def on_send_typing(self):
        self.send_typing_callback()


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

    def _scheduled_start_thinking(self):
        """Legacy hook kept for compatibility; thinking bubble is no longer auto-driven."""
        return

    def load_history(self, count: int, end_index: int = -1):
        self.on_load_history(count, end_index)

    def _fetch_history(self, count, end_index):
        if self.fetch_history_callback:
            history_data, start_index = self.fetch_history_callback(count, end_index)
            self.history_signal.emit(history_data, start_index)