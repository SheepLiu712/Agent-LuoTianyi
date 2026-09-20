"""语音请求的控制异常。"""


class TTSStreamCancelled(Exception):
    """本次语音流已取消，共享引擎仍可处理其他请求。"""
