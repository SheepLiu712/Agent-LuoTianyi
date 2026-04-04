import multiprocessing
import soundfile as sf
import io
import queue
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from ..utils.logger import get_logger
from ..utils.audio_processor import extract_audio_amplitude, decode_from_base64, AudioPlayerStream, calculate_amplitude_from_chunk

if TYPE_CHECKING:
    from ..live2d import Live2dModel

@dataclass
class AudioProperties:
    is_first_audio: bool = True
    samplerate: int = 0
    channels: int = 0 
    subtype: str = None

    def reset(self):
        self.is_first_audio = True
        self.samplerate = 0
        self.channels = 0
        self.subtype = None

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

class MultiMediaStream:
    def __init__(self):
        self.logger = get_logger(__class__.__name__)
        self.model = None
        self.audio_queue_in = multiprocessing.Queue()
        self.audio_queue_out = multiprocessing.Queue()
        self.audio_process = multiprocessing.Process(
            target=run_audio_player_worker, 
            args=(self.audio_queue_in, self.audio_queue_out),
            daemon=True
        ) # 主要处理的进程

        # 嘴型处理相关
        self._mouth_thread: threading.Thread | None = None # 处理嘴型的线程
        self._mouth_queue: queue.Queue | None = None # 嘴型数据队列
        self._stop_mouth_event: threading.Event | None = None # 停止嘴型线程的事件
        
        self.local_audio_properties: AudioProperties | None = None

    def start(self):
        self.audio_process.start()

    def feed(self, audio_data_base64: str):
        audio_data = decode_from_base64(audio_data_base64)
        self._append_audio_stream(audio_data)

    def finish_one_sentense(self):
        self._close_audio_stream(wait_audio_finish=True)


    def _open_audio_stream_if_needed(self):
        if self._mouth_thread and self._mouth_thread.is_alive():
            return

        self.local_audio_properties = AudioProperties()
        self._mouth_queue = queue.Queue()
        self._stop_mouth_event = threading.Event()
        self._init_mouth_value = self.model.GetParameterValue("ParamMouthOpenY") if self.model else 0

        self._mouth_thread = threading.Thread(
            target=self._mouth_move_stream,
            args=(self._init_mouth_value, self._mouth_queue, self._stop_mouth_event),
            daemon=True,
        )
        self._mouth_thread.start()


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
                    if self.model:
                        self.model.SetParameterValue("ParamMouthOpenY", target_val, weight=0.3)
                    time.sleep(1 / fps)

            except queue.Empty:
                continue
                
        if self.model:
            self.model.SetParameterValue("ParamMouthOpenY", init_value, weight=1)

    def _append_audio_stream(self, audio_data: bytes):
        self._open_audio_stream_if_needed()
        amps = []
        if self.local_audio_properties.is_first_audio:
            try:
                with sf.SoundFile(io.BytesIO(audio_data)) as f:
                    self.local_audio_properties.samplerate = f.samplerate
                    self.local_audio_properties.channels = f.channels
                    self.local_audio_properties.subtype = f.subtype
            except Exception as exc:
                self.logger.error(f"Header parse error: {exc}")

            amps = extract_audio_amplitude(audio_data, fps=60)
            self.local_audio_properties.is_first_audio = False
        elif self.local_audio_properties.samplerate > 0:
            amps = calculate_amplitude_from_chunk(
                audio_data,
                self.local_audio_properties.samplerate,
                self.local_audio_properties.channels,
                self.local_audio_properties.subtype,
                fps=60,
            )

        if amps is not None and self._mouth_queue is not None:
            self._mouth_queue.put(amps)

        self.audio_queue_in.put({"cmd": "append", "data": audio_data})

    def _close_audio_stream(self, wait_audio_finish: bool):
        if wait_audio_finish and self._mouth_thread and self._mouth_thread.is_alive():
            self.audio_queue_in.put({"cmd": "wait_finish"})
            try:
                _ = self.audio_queue_out.get(timeout=15)
            except Exception:
                pass

        if self._stop_mouth_event:
            self._stop_mouth_event.set()
        if self._mouth_thread:
            self._mouth_thread.join(timeout=1.0)

        self._mouth_thread = None
        self._stop_mouth_event = None
        self._mouth_queue = None
        if self.local_audio_properties:
            self.local_audio_properties.reset()