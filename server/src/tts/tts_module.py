import os
import json
import asyncio
import requests
from typing import Dict, Any, Optional
from ..utils.logger import get_logger
from .tts_server import TTSServer

class ReferenceAudio:
    def __init__(self, audio_path: str, lyrics: str) -> None:
        self.audio_path = audio_path
        self.lyrics = lyrics

    def __repr__(self):
        return f"ReferenceAudio(audio_path={self.audio_path}, lyrics={self.lyrics})"
    
    def __str__(self):
        return self.__repr__()

class TTSModule:
    """
    Client module for interacting with the running GPT-SoVITS server.
    Handles reference audio management and speech synthesis requests.
    """
    def __init__(self, tts_config: Dict[str, Any], api_url: str) -> None:
        self.logger = get_logger("TTSModule")
        self.config = tts_config
        self.api_url = api_url
        
        self.character_name = tts_config.get("character_name", "LuoTianyi")
        self.language = tts_config.get("language", "zh")

        self.tone_reference_audio_projection: Dict[str, str] = self._prepare_tone_reference_audio_projection(
            tts_config.get("interface_config_path", "config/tts_interface_config.json")
        )
        self.reference_audio: Dict[str, ReferenceAudio] = self._prepare_reference_audio(
            tts_config.get("reference_audio_dir", ""), tts_config.get("reference_audio_lyrics", "")
        )
        self.logger.info(f"TTSModule initialized with API URL: {self.api_url}")

    def _prepare_reference_audio(self, reference_audio_dir: str, reference_audio_lyrics: str) -> Dict[str, ReferenceAudio]:
        if not os.path.exists(reference_audio_lyrics):
             self.logger.warning(f"Reference audio lyrics file not found: {reference_audio_lyrics}")
             return {}
             
        try:
            with open(reference_audio_lyrics, "r", encoding="utf-8") as f:
                reference_audio_lyrics_data: Dict[str, str] = json.load(f)
        except Exception as e:
            self.logger.error(f"Failed to load reference lyrics: {e}")
            return {}

        reference_audio = {}
        if os.path.exists(reference_audio_dir):
            for reference_audio_file in os.listdir(reference_audio_dir):
                if reference_audio_file.lower().endswith((".wav", ".mp3")):
                    audio_path = os.path.join(reference_audio_dir, reference_audio_file)
                    reference_audio_file_name = reference_audio_file.rsplit(".", 1)[0]
                    # Use absolute path for the server to access local files if server is local
                    abs_audio_path = os.path.abspath(audio_path)
                    reference_audio[reference_audio_file_name] = ReferenceAudio(
                        audio_path=abs_audio_path, 
                        lyrics=reference_audio_lyrics_data.get(reference_audio_file_name, "")
                    )
        self.logger.info(f"Loaded {len(reference_audio)} reference audio files.")
        return reference_audio
    
    def _prepare_tone_reference_audio_projection(self, config_path: str) -> Dict[str, str]:
        if not os.path.exists(config_path):
            self.logger.warning(f"Tone reference audio config file not found: {config_path}")
            return {}
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config_data = json.load(f)
            return config_data.get("tone_ref_audio_projection", {})
        except Exception as e:
            self.logger.error(f"Failed to load tone reference audio projection: {e}")
            return {}

    def get_available_tones(self) -> list[str]:
        """获取可用的语气列表"""
        return list(self.tone_reference_audio_projection.keys())

    async def synthesize_speech_with_tone(self, text: str, tone: str) -> bytes:
        """
        根据指定语气合成语音, 异步调用，返回音频数据 bytes
        
        Args:
            text: 要合成的文本
            tone: 语气 key
            
        Returns:
            bytes: WAV 格式音频数据
        """
        ref_audio_name = self.tone_reference_audio_projection.get(tone)
        if not ref_audio_name:
            self.logger.warning(f"Tone '{tone}' not found, falling back to default or first available.")
            if self.tone_reference_audio_projection:
                 ref_audio_name = next(iter(self.tone_reference_audio_projection.values()))
            else:
                 raise ValueError("No reference audio available.")

        return await self.synthesize_speech(text, ref_audio_name)

    async def synthesize_speech(self, text: str, ref_audio_key: str) -> bytes:
        """
        合成语音的核心方法 (异步)
        
        Args:
            text: 要合成的文本
            ref_audio_key: 参考音频的键名 (文件名不含后缀)
            
        Returns:
            bytes: WAV 格式音频数据
        """
        ref_audio_obj = self.reference_audio.get(ref_audio_key)
        if ref_audio_obj is None:
            raise ValueError(f"Reference audio '{ref_audio_key}' not found.")

        payload = {
            "text": text,
            "text_lang": self.language,
            "ref_audio_path": ref_audio_obj.audio_path,
            "prompt_lang": self.language, 
            "prompt_text": ref_audio_obj.lyrics,
            "text_split_method": "cut5",
            "batch_size": 1,
            "media_type": "wav",
            "streaming_mode": False
        }

        self.logger.debug(f"Sending TTS request for text: {text[:20]}...")
        
        try:
            # Use asyncio.to_thread to make the blocking requests.post non-blocking
            def _do_request():
                return requests.post(f"{self.api_url}/tts", json=payload, timeout=600)

            response = await asyncio.to_thread(_do_request)
            
            if response.status_code == 200:
                self.logger.info(f"TTS synthesis successful for text: {text[:20]}...")
                return response.content
            else:
                self.logger.error(f"TTS API Error: {response.status_code} - {response.text}")
                raise Exception(f"TTS API failed with status {response.status_code}")
        except Exception as e:
            self.logger.error(f"TTS Request failed: {e}")
            raise

    def encode_audio_to_base64(self, audio_bytes: bytes) -> str:
        """将音频 bytes 编码为 base64 字符串"""
        if not audio_bytes:
            return ""
        import base64
        return base64.b64encode(audio_bytes).decode("utf-8")

tts_server = None
tts_module = None

def init_tts_module(tts_config: Dict[str, Any]) -> TTSModule:
    global tts_server, tts_module
    server_config_path = tts_config.get("server_config_path", "config/tts_infer.yaml")
    tts_server = TTSServer(config_path=server_config_path)
    tts_server.start()
    api_url = tts_server.get_api_url()
    # api_url = "http://127.0.0.1:50021"
    tts_module = TTSModule(tts_config=tts_config, api_url=api_url)
    return tts_module