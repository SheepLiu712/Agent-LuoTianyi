import librosa
import numpy as np

def extract_audio_amplitude(wav_path: str, fps: int = 30) -> np.ndarray:
    """
    从音频文件中提取振幅（音量）信息，用于口型同步。
    
    Args:
        wav_path: 音频文件路径
        fps: 每秒采样的帧数，通常与Live2D模型的刷新率一致（如30或60）
        
    Returns:
        numpy.ndarray: 归一化后的振幅数组，值范围 [0, 1]
    """
    # 加载音频，sr=None 保持原始采样率
    y, sr = librosa.load(wav_path, sr=None)
    
    # 计算 hop_length 以匹配目标 fps
    # hop_length 是两帧之间的样本数
    hop_length = int(sr / fps)
    
    # 计算 RMS (Root Mean Square) 振幅
    # frame_length 通常设为 hop_length 或稍大
    rms = librosa.feature.rms(y=y, frame_length=hop_length, hop_length=hop_length)[0]
    
    # 归一化处理
    # 可以根据需要调整归一化策略，例如使用对数刻度或设置阈值
    if np.max(rms) > 0:
        rms = rms / np.max(rms)
        
    # 平滑处理（可选），避免嘴巴抖动过快
    # rms = np.convolve(rms, np.ones(3)/3, mode='same')
    
    return rms
