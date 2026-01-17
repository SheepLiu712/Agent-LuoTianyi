import os
import json
import datetime
from typing import Dict, Any, Optional
from ..utils.logger import get_logger
from queue import PriorityQueue
import time
import threading
import sys
import requests
import atexit

def run_server_silent(config_path, host, port):
    """Wrapper to run the server with stdout/stderr redirected to devnull."""
    import sys
    import os
    # # Redirect stdout and stderr to devnull to suppress output
    # sys.stdout = open(os.devnull, 'w')
    # sys.stderr = open(os.devnull, 'w')
    
    from src.GPT_SoVITS.api_v2 import run_server
    run_server(config_path, host, port)

class TTSTask:
    def __init__(self, task_id: str, text: str, tone: str) -> None:
        self.task_id = task_id
        self.text = text
        self.tone = tone
        self.save_path: str | None = None

    def __repr__(self):
        return f"TTSTask(task_id={self.task_id}, text={self.text}, tone={self.tone})"
    
    def __str__(self):
        return self.__repr__()

    def __lt__(self, other):
        return self.task_id < other.task_id

class ReferenceAudio:
    def __init__(self, audio_path: str, lyrics: str) -> None:
        self.audio_path = audio_path
        self.lyrics = lyrics

    def __repr__(self):
        return f"ReferenceAudio(audio_path={self.audio_path}, lyrics={self.lyrics})"
    
    def __str__(self):
        return self.__repr__()


class TTSModule:
    def __init__(self, tts_config: Dict[str, Any]) -> None:
        self.logger = get_logger(__name__)
        self.character_name = tts_config.get("character_name", "LuoTianyi")
        self.language = tts_config.get("language", "zh")
        self.save_dir = tts_config.get("save_dir", "data/tts_output")
        self.config = tts_config
        
        # Ensure save directory exists
        os.makedirs(self.save_dir, exist_ok=True)

        self.tone_reference_audio_projection: Dict[str, str] = tts_config.get("tone_ref_audio_projection", None)
        self.reference_audio: Dict[str, ReferenceAudio] = self._prepare_reference_audio(
            tts_config.get("reference_audio_dir", ""), tts_config.get("reference_audio_lyrics", "")
        )

        # GPT-SoVITS Server Configuration
        self.api_port = 9880
        self.api_url = f"http://127.0.0.1:{self.api_port}"
        self.server_process = None
        
        # Start the server
        self._start_server()

        self.task_queue = PriorityQueue()
        self.output_queue: Dict[str, TTSTask] = {}
        self.working_thread = threading.Thread(target=self.spin)
        self.working_thread.daemon = True
        self.working_thread.start()
        
        # Register cleanup
        atexit.register(self._stop_server)

    def _prepare_reference_audio(self, reference_audio_dir: str, reference_audio_lyrics: str) -> Dict[str, ReferenceAudio]:
        if not os.path.exists(reference_audio_lyrics):
             self.logger.warning(f"Reference audio lyrics file not found: {reference_audio_lyrics}")
             return {}
             
        with open(reference_audio_lyrics, "r", encoding="utf-8") as f:
            reference_audio_lyrics_data: Dict[str, str] = json.load(f)

        reference_audio = {}
        if os.path.exists(reference_audio_dir):
            for reference_audio_file in os.listdir(reference_audio_dir):
                if reference_audio_file.endswith(".wav") or reference_audio_file.endswith(".mp3"):
                    audio_path = os.path.join(reference_audio_dir, reference_audio_file)
                    reference_audio_file_name = reference_audio_file.rsplit(".", 1)[0]
                    # Use absolute path for the server
                    abs_audio_path = os.path.abspath(audio_path)
                    reference_audio[reference_audio_file_name] = ReferenceAudio(
                        audio_path=abs_audio_path, 
                        lyrics=reference_audio_lyrics_data.get(reference_audio_file_name, "")
                    )
        self.logger.info(f"Loaded {len(reference_audio)} reference audio files.")
        return reference_audio

    def _kill_process_on_port(self, port):
        """Kill any process listening on the specified port."""
        try:
            import psutil
            for proc in psutil.process_iter():
                try:
                    for conn in proc.net_connections():
                        if conn.laddr.port == port:
                            self.logger.warning(f"Port {port} is in use by process {proc.pid} ({proc.name()}). Killing it...")
                            proc.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
        except ImportError:
            self.logger.error("psutil not installed, cannot kill process on port.")
        except Exception as e:
            self.logger.error(f"Error killing process on port {port}: {e}")

    def _start_server(self):
        """Start the GPT-SoVITS API server in a separate process."""
        self._kill_process_on_port(self.api_port)
        config_path = self.config.get("server_config_path", os.path.join("config", "tts_infer.yaml"))

        if not os.path.exists(config_path):
            self.logger.error(f"Config file not found at {config_path}")
            raise FileNotFoundError(f"Config file not found at {config_path}")
        
        self.logger.info("Starting GPT-SoVITS server in a separate process...")
        
        # Import here to avoid top-level dependency issues
        # from src.GPT_SoVITS.api_v2 import run_server # No longer needed here
        import multiprocessing

        self.server_process = multiprocessing.Process(
            target=run_server_silent,
            args=(config_path, "127.0.0.1", self.api_port),
            daemon=True
        )
        self.server_process.start()
        
        if not self._wait_for_server():
            self.logger.error("Failed to start GPT-SoVITS server.")
            if self.server_process.is_alive():
                self.server_process.terminate()
        else:
            self.logger.info("GPT-SoVITS server started successfully.")

    def _wait_for_server(self, timeout=60) -> bool:
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                response = requests.get(f"{self.api_url}/control", params={"command": "health_check"}, timeout=1)
                if response.status_code in [200, 400, 422]: # 400/422 means server is up but maybe command invalid, which is fine for connectivity check
                    return True
            except requests.exceptions.ConnectionError:
                pass
            except Exception as e:
                self.logger.debug(f"Polling error: {e}")
            
            if self.server_process and not self.server_process.is_alive():
                self.logger.error("Server process died unexpectedly.")
                return False

            time.sleep(1)
        return False

    def _stop_server(self):
        if self.server_process:
            self.logger.info("Stopping GPT-SoVITS server...")
            try:
                requests.get(f"{self.api_url}/control", params={"command": "exit"}, timeout=1)
            except:
                pass
            
            if hasattr(self.server_process, 'join'):
                self.server_process.join(timeout=5)
                if self.server_process.is_alive():
                    self.logger.warning("GPT-SoVITS server did not exit gracefully, terminating...")
                    self.server_process.terminate()
                    self.server_process.join()
            
            self.server_process = None

    def spin(self):
        """处理TTS任务队列，合成语音并将结果放入输出队列"""
        while True:
            if not self.task_queue.empty():
                _, task = self.task_queue.get()

                self.logger.info(f"Processing TTS task: {task}")
                try:
                    save_path = self.synthesize_speech_with_tone(task.text, task.tone)
                    task.save_path = save_path
                    self.output_queue[task.task_id] = task
                except Exception as e:
                    self.logger.error(f"Failed to process TTS task {task.task_id}: {e}")
                    # Optionally mark task as failed or retry
            else:
                time.sleep(0.1)
    
    def add_task(self, text: str, tone: str, index: int) -> str:
        """添加TTS任务到队列"""
        task_id = datetime.datetime.now().strftime("%H%M%S") + str(index)
        task = TTSTask(task_id=task_id, text=text, tone=tone)
        self.task_queue.put((task_id, task))
        return task_id

    def get_task_result(self, task_id: str) -> str | None:
        """获取TTS任务结果"""
        task = self.output_queue.pop(task_id, None)
        if task:
            return task.save_path
        else:
            return None

    def synthesize_speech(self, text: str, ref_audio: ReferenceAudio | str) -> str:
        """合成语音并保存到指定路径"""
        if isinstance(ref_audio, str):
            ref_audio_obj = self.reference_audio.get(ref_audio)
            if ref_audio_obj is None:
                raise ValueError(f"Reference audio '{ref_audio}' not found.")
            ref_audio = ref_audio_obj

        payload = {
            "text": text,
            "text_lang": self.language,
            "ref_audio_path": ref_audio.audio_path,
            "prompt_lang": self.language, # Assuming prompt lang is same as target lang for now
            "prompt_text": ref_audio.lyrics,
            "text_split_method": "cut5",
            "batch_size": 1,
            "media_type": "wav",
            "streaming_mode": False
        }

        self.logger.debug(f"Sending TTS request: {payload}")
        
        try:
            response = requests.post(f"{self.api_url}/tts", json=payload)
            
            if response.status_code == 200:
                save_path = os.path.join(self.save_dir, datetime.datetime.now().strftime("%Y%m%d%H%M%S") + ".wav")
                with open(save_path, "wb") as f:
                    f.write(response.content)
                self.logger.info(f"Audio saved to {save_path}")
                return save_path
            else:
                self.logger.error(f"TTS API Error: {response.status_code} - {response.text}")
                raise Exception(f"TTS API failed with status {response.status_code}")
        except Exception as e:
            self.logger.error(f"Request failed: {e}")
            raise

    def get_available_tones(self) -> list[str]:
        """获取可用的语气列表"""
        if self.tone_reference_audio_projection is None:
            raise ValueError("tone_ref_audio_projection not configured in TTSModule")
        return list(self.tone_reference_audio_projection.keys())
    
    def synthesize_speech_with_tone(self, text: str, tone: str) -> str:
        """根据指定语气合成语音"""
        if self.tone_reference_audio_projection is None:
            raise ValueError("tone_ref_audio_projection not configured in TTSModule")
        ref_audio_name = self.tone_reference_audio_projection.get(tone, None)
        if ref_audio_name is None:
            raise ValueError(f"Tone '{tone}' not found in tone_reference_audio_projection")
        return self.synthesize_speech(text, ref_audio_name)
    
    def play_audio(self, audio_path: str) -> None:
        """播放音频文件"""
        if sys.platform == "win32":
            import winsound
            try:
                winsound.PlaySound(audio_path, winsound.SND_FILENAME)
            except Exception as e:
                self.logger.error(f"Failed to play audio: {e}")
        else:
            self.logger.warning("Auto-play not supported on this platform.")
