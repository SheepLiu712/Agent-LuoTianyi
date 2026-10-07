"""媒体存储与解析共享的 M4A/AAC-LC 内容校验。"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from io import BytesIO

from mutagen import MutagenError
from mutagen.mp4 import MP4

from .media_resolver import MediaResolutionError, MediaResolutionErrorCode

_MP4_BRANDS = {b"isom", b"mp41", b"mp42", b"M4A ", b"M4B "}


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
    try:
        _validate_audio_tracks(data, media_id)
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


def _boxes(data: memoryview) -> list[tuple[bytes, memoryview]]:
    """Read one box level with explicit parent bounds; never scan media bytes for signatures."""
    boxes = []
    offset = 0
    while offset < len(data):
        size, kind = struct.unpack_from(">I4s", data, offset)
        header = 8
        if size == 1:
            size = struct.unpack_from(">Q", data, offset + 8)[0]
            header = 16
        elif size == 0:
            size = len(data) - offset
        if size < header or size > len(data) - offset:
            raise ValueError("invalid MP4 box bounds")
        boxes.append((kind, data[offset + header : offset + size]))
        offset += size
    return boxes


def _one(boxes: list[tuple[bytes, memoryview]], kind: bytes) -> memoryview:
    matches = [payload for name, payload in boxes if name == kind]
    if len(matches) != 1:
        raise ValueError("missing or ambiguous MP4 box")
    return matches[0]


def _validate_audio_tracks(data: bytes, media_id: str) -> None:
    boxes = _boxes(memoryview(data))
    ftyp = _one(boxes, b"ftyp")
    if len(ftyp) < 8 or len(ftyp) % 4:
        raise ValueError("invalid MP4 file type")
    brands = {bytes(ftyp[:4])} | {bytes(ftyp[i : i + 4]) for i in range(8, len(ftyp), 4)}
    if not brands & _MP4_BRANDS or b"M4P " in brands:
        _raise(MediaResolutionErrorCode.UNSUPPORTED_TYPE, media_id)
    # Voice recordings contain one unencrypted audio track. Do not trust an M4A
    # brand or Mutagen's first audio track while ignoring other (e.g. video) tracks.
    tracks = [payload for kind, payload in _boxes(_one(boxes, b"moov")) if kind == b"trak"]
    if len(tracks) != 1:
        _raise(MediaResolutionErrorCode.UNSUPPORTED_TYPE, media_id)
    mdia = _boxes(_one(_boxes(tracks[0]), b"mdia"))
    handler = _one(mdia, b"hdlr")
    if len(handler) < 12 or bytes(handler[8:12]) != b"soun":
        _raise(MediaResolutionErrorCode.UNSUPPORTED_TYPE, media_id)
    stbl = _boxes(_one(_boxes(_one(mdia, b"minf")), b"stbl"))
    _validate_sample_entry(_one(stbl, b"stsd"), media_id)


def _validate_sample_entry(stsd: memoryview, media_id: str) -> None:
    version_flags, count = struct.unpack_from(">II", stsd)
    entries = _boxes(stsd[8:])
    if version_flags != 0 or count != 1 or len(entries) != 1 or entries[0][0] != b"mp4a":
        _raise(MediaResolutionErrorCode.UNSUPPORTED_TYPE, media_id)
    sample = entries[0][1]
    # ISO AudioSampleEntry v0 has 28 bytes before child boxes. Encrypted entries
    # (enca/drms) and protection information (sinf) must never pass as plain AAC.
    if len(sample) < 28 or bytes(sample[8:10]) != b"\0\0":
        _raise(MediaResolutionErrorCode.UNSUPPORTED_TYPE, media_id)
    children = _boxes(sample[28:])
    if any(kind == b"sinf" for kind, _ in children):
        _raise(MediaResolutionErrorCode.UNSUPPORTED_TYPE, media_id)
    _one(children, b"esds")


def _raise(code: MediaResolutionErrorCode, media_id: str) -> None:
    raise MediaResolutionError(code=code, media_id=media_id)
