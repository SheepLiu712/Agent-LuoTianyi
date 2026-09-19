from __future__ import annotations

import wave
from enum import Enum
from pathlib import Path


class PlaybackResult(str, Enum):
    COMPLETED = "completed"
    DEVICE_UNAVAILABLE = "device_unavailable"
    INTERRUPTED = "interrupted"


class PlaybackBackend:
    """无 GUI 的可替换播放后端 interface（S4 契约）。"""

    def play(self, path: Path) -> PlaybackResult:  # pragma: no cover - interface
        raise NotImplementedError


class DefaultPlaybackBackend(PlaybackBackend):
    """生产默认后端：格式校验由调用方完成后，使用当前平台已有播放能力。

    无平台播放能力或设备不可用时返回 DEVICE_UNAVAILABLE，不得伪装成功；
    不依赖 Qt、Live2D 或 GUI 播放状态。
    """

    def play(self, path: Path) -> PlaybackResult:
        try:
            import winsound
        except ImportError:
            return PlaybackResult.DEVICE_UNAVAILABLE
        try:
            winsound.PlaySound(str(path), winsound.SND_FILENAME)
        except (RuntimeError, OSError):
            return PlaybackResult.DEVICE_UNAVAILABLE
        return PlaybackResult.COMPLETED


def read_wav_format(path: Path) -> str | None:
    """返回可解码音频的格式小写名（S4 仅支持 WAV）；不可解码时返回 None。"""
    try:
        with wave.open(str(path), "rb") as wav:
            wav.getnframes()
            wav.getframerate()
    except (wave.Error, OSError, EOFError, ValueError):
        return None
    return "wav"
