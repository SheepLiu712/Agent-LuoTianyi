import soundfile as sf
import numpy as np
import winsound
import base64
from .logger import get_logger
import io
import os
from datetime import datetime
import time

logger = get_logger("audio_processor")


def apply_volume_to_pcm_bytes(
    data: bytes,
    gain: float,
    sample_width: int | None = None,
    subtype: str | None = None,
) -> bytes:
    if not data:
        return data
    if gain == 1.0:
        return data

    gain = max(0.0, float(gain))
    if sample_width is None:
        if subtype == "PCM_U8":
            sample_width = 1
        elif subtype == "PCM_24":
            sample_width = 3
        elif subtype in ("PCM_16", None):
            sample_width = 2
        else:
            sample_width = 4

    try:
        if subtype == "FLOAT":
            arr = np.frombuffer(data, dtype=np.float32)
            arr = np.clip(arr * gain, -1.0, 1.0)
            return arr.astype(np.float32).tobytes()

        if sample_width == 1:
            # 8-bit PCM is unsigned in WAV.
            arr = np.frombuffer(data, dtype=np.uint8).astype(np.float32)
            arr = (arr - 128.0) * gain + 128.0
            arr = np.clip(arr, 0.0, 255.0)
            return arr.astype(np.uint8).tobytes()

        if sample_width == 2:
            arr = np.frombuffer(data, dtype=np.int16).astype(np.float32)
            arr = np.clip(arr * gain, -32768.0, 32767.0)
            return arr.astype(np.int16).tobytes()

        if sample_width == 3:
            raw = np.frombuffer(data, dtype=np.uint8)
            if len(raw) % 3 != 0:
                return data
            n = len(raw) // 3
            b = raw.reshape(n, 3)
            vals = (
                b[:, 0].astype(np.int32)
                | (b[:, 1].astype(np.int32) << 8)
                | (b[:, 2].astype(np.int32) << 16)
            )
            sign = vals & 0x800000
            vals = vals - (sign << 1)
            vals = np.clip(vals.astype(np.float32) * gain, -8388608.0, 8388607.0).astype(np.int32)
            out = np.empty((n, 3), dtype=np.uint8)
            out[:, 0] = vals & 0xFF
            out[:, 1] = (vals >> 8) & 0xFF
            out[:, 2] = (vals >> 16) & 0xFF
            return out.tobytes()

        if sample_width == 4:
            arr = np.frombuffer(data, dtype=np.int32).astype(np.float64)
            arr = np.clip(arr * gain, -2147483648.0, 2147483647.0)
            return arr.astype(np.int32).tobytes()
    except Exception as e:
        logger.error(f"Failed to apply volume: {e}")

    return data

def extract_audio_amplitude(wav: str | bytes, fps: int = 30) -> np.ndarray:
    """
    从音频文件中提取振幅（音量）信息，用于口型同步。
    
    Args:
        wav: 音频文件路径或字节流
        fps: 每秒采样的帧数，通常与Live2D模型的刷新率一致（如30或60）
        
    Returns:
        numpy.ndarray: 归一化后的振幅数组，值范围 [0, 1]
    """
    # 加载音频，sr=None 保持原始采样率
    try:
        if isinstance(wav, bytes):
            # soundfile.read supports file-like objects
            y, sr = sf.read(io.BytesIO(wav))
        else:
            y, sr = sf.read(wav)
    except Exception as e:
        logger.error(f"Failed to load audio with soundfile: {e}")
        return np.array([0.0])

    # 如果是多声道，取平均值转为单声道
    if y.ndim > 1:
        y = np.mean(y, axis=1)

    # 计算 hop_length 以匹配目标 fps
    # hop_length 是两帧之间的样本数
    hop_length = int(sr / fps)
    
    if hop_length <= 0:
        return np.array([0.0])

    # 计算 RMS (Root Mean Square) 振幅
    # Manual sliding window RMS
    # Pad y to handle the last frame
    pad_width = hop_length - (len(y) % hop_length)
    if pad_width != hop_length:
        y = np.pad(y, (0, pad_width), mode='constant')
        
    # Reshape to (num_frames, hop_length) and calculate RMS
    # This is a non-overlapping window approximation, which is close enough for lip sync
    # If we want overlapping, we'd need stride_tricks, but simple non-overlapping is faster and usually fine.
    # Librosa's rms uses centered frames which overlap.
    # For lip sync, simple block RMS is often sufficient.
    
    num_frames = len(y) // hop_length
    frames = y.reshape(num_frames, hop_length)
    rms = np.sqrt(np.mean(frames**2, axis=1))
    
    # 归一化处理
    # 可以根据需要调整归一化策略，例如使用对数刻度或设置阈值
    if np.max(rms) > 0:
        rms = rms / np.max(rms)
        
    # 平滑处理（可选），避免嘴巴抖动过快
    # rms = np.convolve(rms, np.ones(3)/3, mode='same')
    
    return rms

def decode_from_base64(base64_str: str) -> bytes:
    """
    从 Base64 编码的字符串解码为音频字节流。
    
    Args:
        base64_str: Base64 编码的音频字符串
        
    Returns:
        bytes: 解码后的音频数据
    """
    if not base64_str:
        return b""
    try:
        return base64.b64decode(base64_str)
    except Exception as e:
        logger.error(f"Error decoding base64 audio: {e}")
        return b""

def save_to_wav(wav_data: bytes) -> str:
    """
    将音频字节流保存为 WAV 文件。
    
    Args:
        wav_data: 音频数据的字节流
    Returns:
        str: 保存的文件路径
    """
    cwd = os.getcwd()
    output_dir = os.path.join(cwd, "temp", "tts_outputs")
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join(output_dir, timestamp + ".wav")
    with open(output_path, "wb") as f:
        f.write(wav_data)
    logger.info(f"Saved WAV file to {output_path}")
    return output_path

HAS_WINSOUND = True

class AudioPlayerStream:
    """
    流式音频播放器。
    类似于 Web 端的 MSE (MediaSource Extensions)，支持 appendBuffer。
    """
    def __init__(self):
        try:
            import pyaudio
            self.p = pyaudio.PyAudio()
            self.has_pyaudio = True
        except ImportError:
            logger.error("PyAudio not installed. Streaming not supported properly.")
            self.has_pyaudio = False
            self.p = None
            
        self.stream = None
        self.header_parsed = False
        self.samplerate = 0
        self.channels = 0
        self.subtype = None # e.g. 'PCM_16'
        self.buffer = io.BytesIO() # buffer for first chunk if needed
        self.volume_gain = 1.0

    def set_volume_gain(self, gain: float):
        self.volume_gain = max(0.0, float(gain))

    def append_buffer(self, data: bytes):
        if not self.has_pyaudio:
            return

        if not self.header_parsed:
            # Attempt to parse header from this chunk (assuming it's the first or start of stream)
            # We use soundfile to detect format
            try:
                with sf.SoundFile(io.BytesIO(data)) as f:
                    self.samplerate = f.samplerate
                    self.channels = f.channels
                    self.subtype = f.subtype
                    initial_audio = f.read(dtype='int16') # Read as int16 for direct output if possible?

                    format_pyaudio = self._get_pyaudio_format(self.subtype)
                    
                    self.stream = self.p.open(format=format_pyaudio,
                                              channels=self.channels,
                                              rate=self.samplerate,
                                              output=True)
                
                    
                    raw_bytes = apply_volume_to_pcm_bytes(
                        initial_audio.tobytes(),
                        gain=self.volume_gain,
                        subtype=self.subtype,
                    )
                    self.stream.write(raw_bytes)
                    self.header_parsed = True
            except Exception as e:
                logger.error(f"Failed to parse header from first chunk: {e}")
                pass
        else:
            self.stream.write(
                apply_volume_to_pcm_bytes(
                    data,
                    gain=self.volume_gain,
                    subtype=self.subtype,
                )
            )

    def wait_until_empty(self):
        # PyAudio 的 write 是阻塞的，但数据写入后到声音从扬声器出来有延迟 (Latency)。
        # stop_stream() 会导致缓冲区数据被丢弃（截断尾音），所以不能用。
        # 这里我们简单地 sleep 掉输出延迟的时间，确保让用户听到最后的声音。
        if self.stream:
            try:
                # 获取输出延迟
                latency = self.stream.get_output_latency()
                # 稍微多等一点点缓冲，避免紧凑
                time.sleep(max(latency, 0.05)) 
            except Exception:
                time.sleep(0.05)

    def _get_pyaudio_format(self, subtype):
        import pyaudio
        if subtype == 'PCM_16':
            return pyaudio.paInt16
        elif subtype == 'PCM_24':
            return pyaudio.paInt24
        elif subtype == 'PCM_32':
            return pyaudio.paInt32
        elif subtype == 'FLOAT':
            return pyaudio.paFloat32
        return pyaudio.paInt16 # Default

    def close(self):
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        # We generally don't terminate PyAudio instance every time if we want to reuse?
        # But here we properly clean up.
        if self.p:
            self.p.terminate()

def calculate_amplitude_from_chunk(data: bytes, samplerate: int, channels: int, subtype: str, fps: int = 60) -> np.ndarray:
    """
    Calculate amplitude for a raw PCM chunk
    """
    # Map subtype to dtype
    dtype = 'int16'
    if subtype == 'FLOAT':
        dtype = 'float32'
    elif subtype == 'PCM_32':
        dtype = 'int32'
    
    try:
        y = np.frombuffer(data, dtype=dtype)
    except ValueError:
        return np.array([0.0]) # Buffer size mismatch?
        
    if channels > 1:
        # Reshape to (N, channels)
        try:
            y = y.reshape(-1, channels)
            y = np.mean(y, axis=1)
        except:
             pass

    # Normalize to -1..1 for calculation if it is int
    if dtype == 'int16':
        y = y / 32768.0
    elif dtype == 'int32':
        y = y / 2147483648.0
        
    # Same RMS logic as extract_audio_amplitude
    hop_length = int(samplerate / fps)
    if hop_length <= 0: return np.array([])
    
    pad_width = hop_length - (len(y) % hop_length)
    if pad_width != hop_length:
        y = np.pad(y, (0, pad_width), mode='constant')
        
    num_frames = len(y) // hop_length
    frames = y.reshape(num_frames, hop_length)
    rms = np.sqrt(np.mean(frames**2, axis=1))

    if np.max(rms) > 0:
        rms = rms / np.max(rms)
    
    # Simple boost
    rms = np.clip(rms * 5 - 1, -1, 1) # simple scaling
    return rms

def play_audio(wav_data: bytes):
    """
    播放音频数据的函数占位符。
    实际实现应根据项目需求使用适当的音频播放库。
    
    Args:
        wav_data: 音频数据的字节流
    """
    if HAS_WINSOUND:
        try:
            # winsound.SND_MEMORY 指示第一个参数是内存中的数据
            # winsound.SND_NODEFAULT 如果找不到声音，不播放系统默认声音
            winsound.PlaySound(wav_data, winsound.SND_MEMORY | winsound.SND_NODEFAULT)
            logger.info("Audio playback finished.")
        except Exception as e:
            logger.error(f"Error playing sound: {e}")
    else:
        # 非 Windows 环境或者是需要跨平台时的备选方案 (需要安装 pyaudio)
        try:
            import pyaudio
            import wave
            import io
            
            logger.info("Using PyAudio for playback...")
            with wave.open(io.BytesIO(wav_data), 'rb') as wf:
                p = pyaudio.PyAudio()
                stream = p.open(format=p.get_format_from_width(wf.getsampwidth()),
                                channels=wf.getnchannels(),
                                rate=wf.getframerate(),
                                output=True)
                
                chunk = 1024
                data = wf.readframes(chunk)
                while len(data) > 0:
                    stream.write(data)
                    data = wf.readframes(chunk)
                
                stream.stop_stream()
                stream.close()
                p.terminate()
            logger.info("Audio playback finished.")
        except ImportError:
            logger.warning("'winsound' not available (not Windows?) and 'pyaudio' not installed.")
            logger.warning("Cannot play audio directly.")
        except Exception as e:
            logger.error(f"Error utilizing PyAudio: {e}")