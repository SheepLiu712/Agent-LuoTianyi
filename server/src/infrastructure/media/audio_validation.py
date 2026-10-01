"""媒体存储与解析共享的 M4A/AAC-LC 内容校验。"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from io import BytesIO

from mutagen import MutagenError
from mutagen.mp4 import MP4

from .media_resolver import MediaResolutionError, MediaResolutionErrorCode

_M4A_BRANDS = {b"M4A ", b"M4B ", b"M4P "}


@dataclass(frozen=True)
class ParsedAudio:
    """服务端从完整音频字节解析出的权威媒体信息。"""

    duration_ms: int
    container: str
    codec: str


def parse_m4a_audio(data: bytes, mime_type: str = "audio/mp4", media_id: str = "audio") -> ParsedAudio:
    """解析并校验固定的 audio/mp4、M4A、AAC-LC 输入。"""
    if mime_type != "audio/mp4":
        _raise(MediaResolutionErrorCode.UNSUPPORTED_TYPE, media_id)
    if not _has_m4a_brand(data):
        _raise(MediaResolutionErrorCode.UNSUPPORTED_TYPE, media_id)
    try:
        audio = MP4(BytesIO(data))
        length = audio.info.length
        codec = audio.info.codec
    except (MutagenError, OSError, OverflowError, struct.error, ValueError):
        _raise(MediaResolutionErrorCode.UNKNOWN, media_id)
    if codec != "mp4a.40.2":
        _raise(MediaResolutionErrorCode.UNSUPPORTED_TYPE, media_id)
    duration_ms = round(length * 1000)
    if duration_ms <= 0:
        _raise(MediaResolutionErrorCode.INVALID_DURATION, media_id)
    return ParsedAudio(duration_ms=duration_ms, container="m4a", codec="aac_lc")


def _has_m4a_brand(data: bytes) -> bool:
    """只读取顶层 ftyp，避免把任意 ISO-BMFF 视频当作 M4A。"""
    if len(data) < 16:
        return False
    size, atom_type = struct.unpack(">I4s", data[:8])
    if atom_type != b"ftyp" or size < 16 or size > len(data):
        return False
    payload = data[8:size]
    brands = {payload[:4]}
    brands.update(payload[offset : offset + 4] for offset in range(8, len(payload) - 3, 4))
    return bool(brands & _M4A_BRANDS)


def _raise(code: MediaResolutionErrorCode, media_id: str) -> None:
    raise MediaResolutionError(code=code, media_id=media_id)
