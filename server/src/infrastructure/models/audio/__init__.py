"""音频理解模型基础设施。"""

from .interface import AudioModelAPIFactory, AudioModelAPIInterface
from .module import AudioModelModule

__all__ = ["AudioModelAPIInterface", "AudioModelAPIFactory", "AudioModelModule"]
