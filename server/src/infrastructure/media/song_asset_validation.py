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
def _audio_duration_seconds(path: str, size: int, modified_ns: int, exact: bool) -> float:
    """Cache probes and decoded durations independently for each audio revision."""
    _ = size, modified_ns
    try:
        duration = float(mediainfo(path).get("duration", ""))
        if not exact and math.isfinite(duration) and duration > 0:
            return duration
    except (TypeError, ValueError, OSError):
        pass

    from pydub import AudioSegment

    duration = len(AudioSegment.from_file(path)) / 1000
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError(f"Audio has no playable duration: {path}")
    return duration


def audio_duration_seconds(audio_path: str | Path, *, exact: bool = False) -> float:
    path = Path(audio_path)
    stat = path.stat()
    if stat.st_size == 0:
        raise ValueError(f"Audio file is empty: {path}")
    return _audio_duration_seconds(str(path.resolve()), stat.st_size, stat.st_mtime_ns, exact)


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


def playable_segments(raw_segments: Any, audio_path: str | Path) -> list[SongSegment]:
    """Validate against rendered audio, recovering metadata errors and clipping only the tail."""
    if not isinstance(raw_segments, list) or not raw_segments:
        return []
    try:
        duration = audio_duration_seconds(audio_path)
        if any(_segment_end(raw) > duration for raw in raw_segments):
            duration = audio_duration_seconds(audio_path, exact=True)
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
