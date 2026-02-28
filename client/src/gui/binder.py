import time
import threading
import queue
import multiprocessing
import io
import soundfile as sf
from PySide6.QtCore import QObject, Signal, QTimer
from ..live2d import Live2dModel, live2d
from ..utils.audio_processor import extract_audio_amplitude, decode_from_base64, play_audio, save_to_wav, AudioPlayerStream, calculate_amplitude_from_chunk
from ..utils.logger import get_logger
import numpy as np
from typing import Dict, Callable

def run_audio_player_worker(queue_in: multiprocessing.Queue, queue_out: multiprocessing.Queue):
    """
    Worker process for audio playback to avoid GIL contention.
    """
    player = AudioPlayerStream()
    
    while True:
        try:
            task = queue_in.get()
            if task is None:
                break
            
            cmd = task.get("cmd")
            if cmd == "append":
                data = task.get("data")
                if data:
                    player.append_buffer(data)
            
            elif cmd == "wait_finish":
                player.wait_until_empty()
                player.header_parsed = False # Reset for new stream
                if queue_out:
                    queue_out.put("finished")
                    
        except Exception as e:
            # print(f"Audio worker error: {e}") 
            pass
    
    player.close()

class AgentBinder(QObject):

    response_signal = Signal(str)
    update_signal = Signal(str)
    delete_signal = Signal()
    free_signal = Signal(bool)
    history_signal = Signal(list, int)  # history_list, current_top_index

    def __init__(self, hear_callback: Callable[[str], Dict], hear_picture_callback: Callable[[str], Dict] = None, history_callback: Callable[[int, int], tuple] = None):
        super().__init__()
        self.logger = get_logger(self.__class__.__name__)
        if hear_callback:
            self.recv_callback = hear_callback
        else:
            raise ValueError("hear_callback must be provided")
        
        self.hear_picture_callback = hear_picture_callback
        self.history_callback = history_callback
    
        self.thinking_thread: threading.Thread | None = None
        self.thinking: bool = False
        self.waiting_package = True
        self.model: Live2dModel | None = None

        # Audio Process
        self.audio_queue_in = multiprocessing.Queue()
        self.audio_queue_out = multiprocessing.Queue()
        self.audio_process = multiprocessing.Process(
            target=run_audio_player_worker, 
            args=(self.audio_queue_in, self.audio_queue_out),
            daemon=True
        )
        self.audio_process.start()

    def _mouth_move_stream(self, init_value, mouth_queue: queue.Queue, stop_event: threading.Event, fps=60):
        while not stop_event.is_set():
            try:
                amps = mouth_queue.get(timeout=0.05)
                if amps is None:
                    break
                
                # We have a chunk of amplitudes (frames)
                start_time = time.time()
                while True:
                    elapesed = time.time() - start_time
                    if elapesed >= len(amps) / fps:
                        break
                    goal_idx = int(elapesed * fps)
                    target_val = amps[goal_idx]
                    self.model.SetParameterValue("ParamMouthOpenY", target_val, weight=0.3)
                    time.sleep(1 / fps)

            except queue.Empty:
                continue
                
        if self.model:
            self.model.SetParameterValue("ParamMouthOpenY", init_value, weight=1)

    def _process_stream_response(self, response_generator):
        """Unified streaming processor for hear and hear_picture"""
        # player running in separate process
        mouth_queue = queue.Queue()
        stop_mouth_event = threading.Event()
        
        init_value = self.model.GetParameterValue("ParamMouthOpenY") if self.model else 0
        mouth_thread = threading.Thread(
            target=self._mouth_move_stream, 
            args=(init_value, mouth_queue, stop_mouth_event)
        )
        mouth_thread.daemon = True
        mouth_thread.start()

        is_first_audio = True
        local_samplerate = 0
        local_channels = 0
        local_subtype = None

        try:
            self.waiting_package = True
            for response in response_generator:
                reply_text = response.get("text", "")
                expression = response.get("expression", None)
                audio_data = decode_from_base64(response.get("audio", b""))
                is_final_package = response.get("is_final_package", False)
                self.waiting_package = False
                if reply_text:
                     self.stop_thinking()
                     self.response_signal.emit(reply_text)
                
                if expression and self.model:
                    self.model.set_expression_by_cmd(expression)

                if audio_data:
                    # Feed Mouth
                    amps = []
                    if is_first_audio:
                         try:
                             with sf.SoundFile(io.BytesIO(audio_data)) as f:
                                 local_samplerate = f.samplerate
                                 local_channels = f.channels
                                 local_subtype = f.subtype
                         except Exception as e:
                             self.logger.error(f"Header parse error: {e}")
                             
                         amps = extract_audio_amplitude(audio_data, fps=60)
                         is_first_audio = False
                    else:
                        if local_samplerate > 0:
                            amps = calculate_amplitude_from_chunk(
                                audio_data, 
                                local_samplerate, 
                                local_channels, 
                                local_subtype,
                                fps=60
                            )

                    # Feed Audio
                    if len(amps) > 0:
                        mouth_queue.put(amps)
                    
                    self.audio_queue_in.put({"cmd": "append", "data": audio_data})
                    
                    if is_final_package:
                        self.audio_queue_in.put({"cmd": "wait_finish"})
                        # Wait for playing to finish
                        _ = self.audio_queue_out.get()
                        
                        is_first_audio = True
                        local_samplerate = 0
                        
                        QTimer.singleShot(100, self.start_thinking)  # 短暂延迟后恢复思考状态，允许UI更新
                else:
                    # Allow UI updates for text-only frames
                    time.sleep(0.01)
                    QTimer.singleShot(100, self.start_thinking)
                self.waiting_package = True    
            self.waiting_package = False

        except Exception as e:
            self.logger.error(f"Stream Error: {e}")
        finally:
            stop_mouth_event.set()
            mouth_thread.join(timeout=1.0)
            self.stop_thinking()
            self.finish_reply()

    def hear(self, text: str):
        """
        接收用户输入的文本，并在后台处理
        """
        def _hear(text:str):
            self.start_thinking()
            try:
                # recv_callback return a generator for SSE
                response_generator = self.recv_callback(text)
                self._process_stream_response(response_generator)
            except Exception as e:
                self.logger.error(f"Error in hear loop: {e}")
                self.stop_thinking()
                self.finish_reply()

        # 使用线程避免阻塞 UI
        thread = threading.Thread(target=_hear, args=(text,))
        thread.daemon = True
        thread.start()

    def hear_picture(self, image_path: str):
        def _hear(image_path:str):
            self.start_thinking()
            try:
                # recv_callback return a generator for SSE
                response_generator = self.hear_picture_callback(image_path)
                self._process_stream_response(response_generator)
            except Exception as e:
                self.logger.error(f"Error in hear loop: {e}")
                self.stop_thinking()
                self.finish_reply()

        # 使用线程避免阻塞 UI
        thread = threading.Thread(target=_hear, args=(image_path,))
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
                for _ in range(10):  # 每个点持续0.5秒
                    if not self.thinking:
                        break
                    time.sleep(0.05)
                self.update_signal.emit("." * (i + 1))

        self.delete_signal.emit()

    def start_thinking(self):
        """
        开始思考，显示动态气泡
        """
        if self.thinking or self.waiting_package == False: # 等到包了，不用思考
            return  # 已经在思考中
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
        if self.thinking_thread:
            self.thinking_thread.join()
            self.thinking_thread = None
    
    def finish_reply(self):
        '''
        本轮对话结束，允许用户输入
        '''
        self.free_signal.emit(True)

    # def start_mouth_move(self, wav: str | bytes, fps: int = 60):
    #     """
    #     开始口型同步
    #     """
    #     if not self.model:
    #         self.logger.warning("No Live2D model loaded for mouth movement.")
    #         return

    #     # # 保存音频数据
    #     # if isinstance(wav, str):
    #     #     wav_path = wav
    #     # else:
    #     #     # 将字节数据保存到temp/tts_output/目录下的临时文件
    #     #     wav_path = save_to_wav(wav)
    #     init_value = self.model.GetParameterValue("ParamMouthOpenY")
    #     amp = np.clip(extract_audio_amplitude(wav=wav, fps=fps) * 6 - 1, -1.0, 1.0)

    #     # 开始口型同步线程
    #     mouth_move_thread = threading.Thread(target=self._mouth_move, args=(init_value, amp, fps), daemon=True)
    #     mouth_move_thread.start()

    # def _mouth_move(self, init_value: float, amp: np.ndarray, fps: int = 60):
    #     if not self.model:
    #         return
        
    #     st_time = time.time()
    #     while True:

    #         elapsed = time.time() - st_time
    #         frame_index = int(elapsed * fps)
    #         if frame_index >= len(amp):
    #             break
    #         weight = np.clip(frame_index / len(amp) - 0.95, 0, 1) * 20
    #         target_value = amp[frame_index] * (1-weight) + init_value * weight  # 最后一段平滑回到初始值
    #         self.model.SetParameterValue("ParamMouthOpenY", target_value, weight=0.3)
    #         time.sleep(1 / fps)

    #     self.model.SetParameterValue("ParamMouthOpenY", init_value, weight=1)