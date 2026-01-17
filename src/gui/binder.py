import time
import threading
from PySide6.QtCore import QObject, Signal
from ..live2d import Live2dModel, live2d
from ..utils.audio_processor import extract_audio_amplitude
import numpy as np

class AgentBinder(QObject):
    response_signal = Signal(str)
    update_signal = Signal(str)
    delete_signal = Signal()
    free_signal = Signal(bool)
    history_signal = Signal(list, int)  # history_list, current_top_index

    def __init__(self, hear_callback, history_callback=None):
        super().__init__()
        if hear_callback:
            self.recv_callback = hear_callback
        else:
            raise ValueError("hear_callback must be provided")
        
        self.history_callback = history_callback
    
        self.thinking_thread: threading.Thread | None = None
        self.thinking: bool = False
        self.model: Live2dModel | None = None

    def hear(self, text: str):
        """
        接收用户输入的文本，并在后台处理
        """
        # 使用线程避免阻塞 UI
        thread = threading.Thread(target=self.recv_callback, args=(text,))
        thread.daemon = True
        thread.start()

    def load_history(self, count: int, end_index: int = -1):
        """
        请求加载历史记录
        :param count: 加载的数量
        :param end_index: 结束索引（不包含），-1表示从最新开始
        """
        if self.history_callback:
            thread = threading.Thread(target=self._fetch_history, args=(count, end_index))
            thread.daemon = True
            thread.start()

    def _fetch_history(self, count, end_index):
        if self.history_callback:
            history_data, start_index = self.history_callback(count, end_index)
            self.history_signal.emit(history_data, start_index)

    def update_bubble(self) -> None:
        '''
        等待LLM响应，在这个过程中在气泡中显示'...'直到响应完成
        '''
        self.response_signal.emit(" ")
        while self.thinking:
            for i in range(3):
                if not self.thinking:
                    break
                self.update_signal.emit("." * (i + 1))
                time.sleep(0.1)

        self.delete_signal.emit()

    def start_thinking(self):
        """
        开始思考，显示动态气泡
        """
        if self.thinking_thread and self.thinking_thread.is_alive():
            return  # 已经在思考中

        self.thinking = True
        self.free_signal.emit(False)
        self.thinking_thread = threading.Thread(target=self.update_bubble)
        self.thinking_thread.daemon = True
        self.thinking_thread.start()

    def stop_thinking(self):
        """
        停止思考，移除动态气泡
        """
        if not self.thinking:
            return  # 不在思考中
        self.thinking = False
        self.free_signal.emit(True)
        if self.thinking_thread:
            self.thinking_thread.join()
            self.thinking_thread = None

    def start_mouth_move(self, wav_path: str):
        """
        开始口型同步
        """
        if self.model:
            self.ready = False
            mouth_move_thread = threading.Thread(target=self._mouth_move, args=(wav_path,), daemon=True)
            mouth_move_thread.start()
            while not self.ready:
                time.sleep(0.01)

    def _mouth_move(self, wav_path: str, fps: int = 60):
        if not self.model:
            return
        
        init_value = self.model.GetParameterValue("ParamMouthOpenY")
        amp = extract_audio_amplitude(wav_path=wav_path, fps=fps)
        correct_factor = (init_value + 6)
        amp = np.clip(amp * correct_factor - 1, -1.0, 1.0) # 调整放大倍数以适应模型, 范围[-1, 1]
        self.ready = True
        st_time = time.time()
        while True:

            elapsed = time.time() - st_time
            frame_index = int(elapsed * fps)
            if frame_index >= len(amp):
                break
            weight = np.clip(frame_index / len(amp) - 0.95, 0, 1) * 20
            target_value = amp[frame_index] * (1-weight) + init_value * weight  # 最后一段平滑回到初始值
            self.model.SetParameterValue("ParamMouthOpenY", target_value, weight=0.3)
            time.sleep(1 / fps)

        self.model.SetParameterValue("ParamMouthOpenY", init_value, weight=1)