import multiprocessing
import soundfile as sf
import io
import queue
import threading
import time
import os
import wave
from dataclasses import dataclass
from typing import Callable
from ..utils.logger import get_logger
from ..utils.audio_processor import (
    extract_audio_amplitude,
    decode_from_base64,
    AudioPlayerStream,
    calculate_amplitude_from_chunk,
    apply_volume_to_pcm_bytes,
)

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
            elif cmd == "set_volume":
                gain = float(task.get("gain", 1.0))
                player.set_volume_gain(gain)
                    
        except Exception as e:
            # print(f"Audio worker error: {e}") 
            pass
    
    player.close()

class MultiMediaStream:
    def __init__(self):
        self.logger = get_logger(__class__.__name__)
        self.model = None
        self.audio_queue_in = multiprocessing.Queue()
        self.audio_queue_out = multiprocessing.Queue(maxsize=1)
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
        self._local_play_thread: threading.Thread | None = None
        self._local_stop_event: threading.Event | None = None
        self._local_play_request_id = 0
        self._local_state_callback: Callable[[str, str], None] | None = None
        self._volume_percent = 70
        self._volume_gain = self._percent_to_gain(self._volume_percent)
        self._state_lock = threading.Lock()

    @staticmethod
    def _percent_to_gain(percent: int) -> float:
        p = max(0, min(100, int(percent)))
        # 70% is treated as baseline level for server audio.
        return p / 70.0 if p > 0 else 0.0

    def _emit_local_playback_state(self, event: str, conv_uuid: str):
        if not self._local_state_callback:
            return
        try:
            self._local_state_callback(event, conv_uuid)
        except Exception as exc:
            self.logger.error(f"Local playback callback error: {exc}")

    def start(self):
        self.audio_process.start()
        self.audio_queue_in.put({"cmd": "set_volume", "gain": self._volume_gain})

    def set_volume_percent(self, percent: int):
        with self._state_lock:
            self._volume_percent = max(0, min(100, int(percent)))
            self._volume_gain = self._percent_to_gain(self._volume_percent)
            gain = self._volume_gain
        self.audio_queue_in.put({"cmd": "set_volume", "gain": gain})

    def set_local_playback_state_callback(self, callback: Callable[[str, str], None] | None):
        self._local_state_callback = callback

    def feed(self, audio_data_base64: str):
        audio_data = decode_from_base64(audio_data_base64)
        if not audio_data:
            return
        # Server audio has higher priority than local replay.
        self._interrupt_local_playback()
        self._append_audio_stream(audio_data)

    def feed_local_wav(self, wav_path: str, conv_uuid: str = "") -> bool:
        if self._mouth_thread is not None:
            return False
        if not wav_path or not os.path.exists(wav_path):
            return False

        with self._state_lock:
            self._local_play_request_id += 1
            request_id = self._local_play_request_id
            self._stop_local_playback_locked(join_timeout=0.4)

            self._local_stop_event = threading.Event()
            self._local_play_thread = threading.Thread(
                target=self._play_local_wav_worker,
                args=(wav_path, conv_uuid, request_id, self._local_stop_event),
                daemon=True,
            )
            self._local_play_thread.start()
            return True

    def stop_local_wav(self) -> bool:
        with self._state_lock:
            self._local_play_request_id += 1
            self._stop_local_playback_locked(join_timeout=0.4)
            return True

    def is_busy(self) -> bool:
        if self._mouth_thread and self._mouth_thread.is_alive():
            return True
        if self._local_play_thread and self._local_play_thread.is_alive():
            return True
        return False

    def _play_local_wav_worker(self, wav_path: str, conv_uuid: str, request_id: int, stop_event: threading.Event):
        pa = None
        stream = None
        try:
            with wave.open(wav_path, "rb") as wf:
                channels = wf.getnchannels()
                sample_width = wf.getsampwidth()
                framerate = wf.getframerate()
                if wf.getnframes() <= 0:
                    return

                import pyaudio

                pa = pyaudio.PyAudio()
                stream = pa.open(
                    format=pa.get_format_from_width(sample_width),
                    channels=channels,
                    rate=framerate,
                    output=True,
                )

                frames_per_chunk = 1024
                while not stop_event.is_set():
                    chunk = wf.readframes(frames_per_chunk)
                    if not chunk:
                        break
                    with self._state_lock:
                        local_gain = self._volume_gain
                    stream.write(
                        apply_volume_to_pcm_bytes(
                            chunk,
                            gain=local_gain,
                            sample_width=sample_width,
                        )
                    )
        except ImportError:
            self.logger.error("PyAudio not installed. Cannot play local wav.")
        except wave.Error as exc:
            self.logger.error(f"Invalid wav file {wav_path}: {exc}")
        except Exception as exc:
            self.logger.error(f"Failed to play local wav file {wav_path}: {exc}")
        finally:
            if stream:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
            if pa:
                try:
                    pa.terminate()
                except Exception:
                    pass

            with self._state_lock:
                # Only clear state when this is still the latest request.
                if request_id == self._local_play_request_id:
                    self._local_play_thread = None
                    self._local_stop_event = None

            state = "stopped" if stop_event.is_set() else "finished"
            self._emit_local_playback_state(state, conv_uuid)

    def _interrupt_local_playback(self):
        with self._state_lock:
            self._stop_local_playback_locked(join_timeout=0.2)

    def _stop_local_playback_locked(self, join_timeout: float):
        if self._local_stop_event:
            self._local_stop_event.set()

        current_thread = threading.current_thread()
        thread = self._local_play_thread
        if thread and thread.is_alive() and thread is not current_thread:
            thread.join(timeout=join_timeout)

        if thread and not thread.is_alive():
            self._local_play_thread = None
            self._local_stop_event = None

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
        if wait_audio_finish:
            # 先保证audio_queue_out为空：
            while not self.audio_queue_out.empty():
                try:
                    self.audio_queue_out.get_nowait()
                except Exception:
                    break
            # 再发结束指令，并等待响应，确保之前的音频数据已经播放完成
            self.audio_queue_in.put({"cmd": "wait_finish"})
            try:
                _ = self.audio_queue_out.get(timeout=120)  # 等待播放完成的信号
            except Exception:
                self.logger.warning("Timeout waiting for audio to finish, forcing stop.")

        if self._stop_mouth_event:
            self._stop_mouth_event.set()
        if self._mouth_thread:
            self._mouth_thread.join(timeout=1.0)

        self._mouth_thread = None
        self._stop_mouth_event = None
        self._mouth_queue = None
        if self.local_audio_properties:
            self.local_audio_properties.reset()