"""通话包内部的解析帧、编码结果和容量配置。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ._audio_codec import WireAudioFrame
from ._control import ControlMessage

CALL_CLOSE_POLICY_VIOLATION = 1008
CALL_CLOSE_TRY_AGAIN_LATER = 1013


class TransportBackpressure(RuntimeError):
    """有限输出容量已满，生产者需等待客户端 ACK 后重试。"""


@dataclass(frozen=True, slots=True)
class InboundFrame:
    """保留原始字节和已校验的控制或音频内容，供会话排序与去重。"""

    seq: int
    kind: Literal["control", "audio"]
    raw: bytes
    control: ControlMessage | None = None
    audio: WireAudioFrame | None = None


@dataclass(frozen=True, slots=True)
class WireOutput:
    """表示一个已编码的文本或二进制报文，二者必须且只能存在一个。"""

    text: str | None = None
    binary: bytes | None = None
    audio_response_id: str | None = None

    def __post_init__(self) -> None:
        if (self.text is None) == (self.binary is None):
            raise ValueError("exactly one wire payload is required")


@dataclass(frozen=True, slots=True)
class TransportConfig:
    """约束乱序窗口、重放缓存、指纹和播放停止元数据的容量。"""

    max_pending_frames: int = 256
    max_pending_bytes: int = 4 * 1024 * 1024
    max_replay_bytes: int = 4 * 1024 * 1024
    max_received_fingerprints: int = 131_072
    max_stop_metadata: int = 4096
    max_response_audio_seconds: int = 30

    def __post_init__(self) -> None:
        for name in (
            "max_pending_frames",
            "max_pending_bytes",
            "max_replay_bytes",
            "max_received_fingerprints",
            "max_stop_metadata",
            "max_response_audio_seconds",
        ):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be a positive integer")
