import os
import pathlib
import json
import datetime
from typing import Dict, Any
from ..utils.logger import get_logger
from collections import deque
from queue import PriorityQueue
import time
import threading
import sys

cwd = os.getcwd()
genie_data_path = pathlib.Path(cwd) / "res" / "tts" / "GenieData"
if genie_data_path.exists():
    os.environ["GENIE_DATA_DIR"] = str(genie_data_path)
else:
    raise FileNotFoundError(f"GenieData directory not found at {genie_data_path}")

import genie_tts as genie


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
        self.onnx_model_dir = tts_config.get("onnx_model_dir", "<PATH_TO_CHARACTER_ONNX_MODEL_DIR>")
        self.language = tts_config.get("language", "zh")
        self.save_dir = tts_config.get("save_dir", "data/tts_output")

        genie.load_character(
            character_name=self.character_name,
            onnx_model_dir=self.onnx_model_dir,
            language=self.language,
        )
        self.tone_reference_audio_projection: Dict[str, str] = tts_config.get("tone_ref_audio_projection", None)
        self.reference_audio: Dict[str, ReferenceAudio] = self._prepare_reference_audio(
            tts_config.get("reference_audio_dir", ""), tts_config.get("reference_audio_lyrics", "")
        )

        self.task_queue = PriorityQueue()
        self.output_queue: Dict[str, TTSTask] = {}
        self.working_thread = threading.Thread(target=self.spin)
        self.working_thread.daemon = True
        self.working_thread.start()
        

    def _prepare_reference_audio(self, reference_audio_dir: str, reference_audio_lyrics: str) -> bytes:
        with open(reference_audio_lyrics, "r", encoding="utf-8") as f:
            reference_audio_lyrics: Dict[str, str] = json.load(f)

        reference_audio = {}
        for reference_audio_file in os.listdir(reference_audio_dir):
            if reference_audio_file.endswith(".wav") or reference_audio_file.endswith(".mp3"):
                audio_path = os.path.join(reference_audio_dir, reference_audio_file)
                reference_audio_file_name = reference_audio_file.rsplit(".", 1)[0]
                reference_audio[reference_audio_file_name] = ReferenceAudio(
                    audio_path=audio_path, lyrics=reference_audio_lyrics.get(reference_audio_file_name, "")
                )
        self.logger.info(f"Loaded {len(reference_audio)} reference audio files.")
        return reference_audio
    
    def spin(self):
        """处理TTS任务队列，合成语音并将结果放入输出队列"""
        while True:
            if not self.task_queue.empty():
                # 改为先进先出 (FIFO)，保证任务号（入队时间）小的先处理
                # 获取最早入队的任务ID
                _, task = self.task_queue.get()

                self.logger.info(f"Processing TTS task: {task}")
                save_path = self.synthesize_speech_with_tone(task.text, task.tone)
                task.save_path = save_path
                self.output_queue[task.task_id] = task
            else:
                time.sleep(0.1)
    
    def add_task(self, text: str, tone: str, index: int) -> str:
        """添加TTS任务到队列

        Args:
            text: 要合成的文本
            tone: 语气名称

        Returns:
            任务ID
        """
        task_id = datetime.datetime.now().strftime("%H%M%S") + str(index)
        task = TTSTask(task_id=task_id, text=text, tone=tone)
        self.task_queue.put((task_id, task))
        return task_id

    def get_task_result(self, task_id: str) -> str | None:
        """获取TTS任务结果

        Args:
            task_id: 任务ID

        Returns:
            合成的音频文件路径，若任务未完成则返回None
        """
        task = self.output_queue.pop(task_id, None)
        if task:
            return task.save_path
        else:
            return None

    def synthesize_speech(self, text: str, ref_audio: ReferenceAudio | str) -> str:
        """合成语音并保存到指定路径

        Args:
            text: 要合成的文本
            ref_audio: 参考音频对象
        """
        if isinstance(ref_audio, str):
            ref_audio = self.reference_audio.get(ref_audio)
            if ref_audio is None:
                raise ValueError(f"Reference audio '{ref_audio}' not found.")
        genie.set_reference_audio(
            character_name=self.character_name,
            audio_path=ref_audio.audio_path,
            audio_text=ref_audio.lyrics,
        )
        save_path = os.path.join(self.save_dir, datetime.datetime.now().strftime("%Y%m%d%H%M%S") + ".wav")
        genie.tts(
            character_name=self.character_name,
            text=text,
            play = False,
            split_sentence= False,
            save_path=save_path,
            )
        genie.wait_for_playback_done()
        return save_path

    def get_available_tones(self) -> list[str]:
        """获取可用的语气列表

        Returns:
            语气列表
        """
        if self.tone_reference_audio_projection is None:
            raise ValueError("tone_ref_audio_projection not configured in TTSModule")
        return list(self.tone_reference_audio_projection.keys())
    
    def synthesize_speech_with_tone(self, text: str, tone: str) -> str:
        """根据指定语气合成语音

        Args:
            text: 要合成的文本
            tone: 语气名称

        Returns:
            合成的音频文件路径
        """
        if self.tone_reference_audio_projection is None:
            raise ValueError("tone_ref_audio_projection not configured in TTSModule")
        ref_audio_name = self.tone_reference_audio_projection.get(tone, None)
        if ref_audio_name is None:
            raise ValueError(f"Tone '{tone}' not found in tone_reference_audio_projection")
        return self.synthesize_speech(text, ref_audio_name)
    
    def play_audio(self, audio_path: str) -> None:
        """播放音频文件

        Args:
            audio_path: 音频文件路径
        """
        if sys.platform == "win32":
            import winsound
            # 使用 winsound 直接播放，不打开外部播放器
            winsound.PlaySound(audio_path, winsound.SND_FILENAME)
        else:
            print("Auto-play not supported on this platform.")