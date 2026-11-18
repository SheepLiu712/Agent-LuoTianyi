"""Validate learned song segments against the audio they will render from."""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydub.utils import mediainfo

from src.domain.music_type import OneLyricLine, SongSegment
from src.utils.logger import get_logger

logger = get_logger(__name__)


@lru_cache(maxsize=512)
def _duration_state(path: str, size: int, modified_ns: int) -> dict:
    """One duration per audio revision; verified values replace estimates."""
    return {}


def _decode_duration(path: Path) -> float:
    from pydub import AudioSegment

    duration = len(AudioSegment.from_file(path)) / 1000
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError(f"Audio has no playable duration: {path}")
    return duration


def _restore_duration(metadata: dict | None, identity: dict) -> float | None:
    record = (metadata or {}).get("audio_duration")
    if not isinstance(record, dict) or any(record.get(key) != value for key, value in identity.items()):
        return None
    try:
        seconds = float(record["seconds"])
        return seconds if math.isfinite(seconds) and seconds > 0 else None
    except (KeyError, TypeError, ValueError):
        return None


def _probe_duration(path: Path) -> float | None:
    try:
        seconds = float(mediainfo(path).get("duration", ""))
        return seconds if math.isfinite(seconds) and seconds > 0 else None
    except (TypeError, ValueError, OSError):
        return None


def audio_duration_seconds(audio_path: str | Path, *, exact: bool = False, metadata: dict | None = None) -> float:
    path = Path(audio_path)
    stat = path.stat()
    if stat.st_size == 0:
        raise ValueError(f"Audio file is empty: {path}")
    identity = {"file": path.name, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    state = _duration_state(str(path.resolve()), stat.st_size, stat.st_mtime_ns)
    restored = _restore_duration(metadata, identity)
    if restored is not None:
        state.update(seconds=restored, verified=True)
    if not state and not exact:
        estimated = _probe_duration(path)
        if estimated is not None:
            state.update(seconds=estimated, verified=False)
    if not state or (exact and not state["verified"]):
        state.update(seconds=_decode_duration(path), verified=True)
    if metadata is not None and state["verified"]:
        metadata["audio_duration"] = {**identity, "seconds": state["seconds"]}
    return state["seconds"]


def _valid_lyrics(raw_lyrics: Any) -> list[OneLyricLine] | None:
    if not isinstance(raw_lyrics, list):
        return None
    normalized: list[OneLyricLine] = []
    for line in raw_lyrics:
        if isinstance(line, OneLyricLine):
            duration, content = line.duration, line.content
        elif isinstance(line, dict):
            duration, content = line.get("duration", 0), line.get("content", "")
        else:
            return None
        try:
            duration = float(duration)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(duration) or duration < 0 or not isinstance(content, str):
            return None
        normalized.append(OneLyricLine(duration=duration, content=content))
    return normalized


def _valid_segment(raw: Any) -> SongSegment | None:
    if isinstance(raw, SongSegment):
        description, start, end, lyrics = raw.description, raw.start_time, raw.end_time, raw.lyrics
    elif isinstance(raw, dict):
        description = raw.get("description")
        start, end, lyrics = raw.get("start_time"), raw.get("end_time"), raw.get("lyrics", [])
    else:
        return None
    if not isinstance(description, str) or not description.strip():
        return None
    try:
        start, end = float(start), float(end)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
        return None
    normalized_lyrics = _valid_lyrics(lyrics)
    if normalized_lyrics is None:
        return None
    return SongSegment(description=description, start_time=start, end_time=end, lyrics=normalized_lyrics)


def _segment_end(raw: Any) -> float:
    try:
        return float(raw.end_time if isinstance(raw, SongSegment) else raw.get("end_time"))
    except (TypeError, ValueError, AttributeError):
        return 0.0


def _clip_tail(segment: SongSegment, duration: float) -> SongSegment | None:
    if segment.start_time >= duration:
        return None
    excess = segment.end_time - duration
    lyrics = list(segment.lyrics)
    while lyrics and excess > 0:
        line = lyrics.pop()
        if line.duration > excess:
            lyrics.append(OneLyricLine(duration=line.duration - excess, content=line.content))
        excess -= line.duration
    return SongSegment(segment.description, segment.start_time, duration, lyrics)


def playable_segments(raw_segments: Any, audio_path: str | Path, *, metadata: dict | None = None) -> list[SongSegment]:
    """Validate against rendered audio, recovering metadata errors and clipping only the tail."""
    if not isinstance(raw_segments, list) or not raw_segments:
        return []
    try:
        duration = audio_duration_seconds(audio_path, metadata=metadata)
        if any(_segment_end(raw) > duration for raw in raw_segments):
            duration = audio_duration_seconds(audio_path, exact=True, metadata=metadata)
    except Exception as exc:
        logger.warning(f"Cannot validate song audio {audio_path}: {type(exc).__name__}: {exc}")
        return []

    valid: list[SongSegment] = []
    descriptions: set[str] = set()
    for index, raw in enumerate(raw_segments):
        segment = _valid_segment(raw)
        reason = "invalid name, time interval or lyrics"
        if segment is not None and segment.end_time > duration:
            reason = f"audio boundary: start={segment.start_time}, end={segment.end_time}, duration={duration}"
            segment = _clip_tail(segment, duration) if index == len(raw_segments) - 1 else None
        if segment is not None and segment.description in descriptions:
            reason = f"duplicate description: {segment.description}"
            segment = None
        if segment is None:
            logger.warning(f"Ignored song segment: audio={audio_path}, index={index + 1}, reason={reason}")
            continue
        descriptions.add(segment.description)
        valid.append(segment)
    return valid
