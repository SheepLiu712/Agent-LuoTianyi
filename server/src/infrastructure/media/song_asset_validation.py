"""Validate learned song segments against the audio they will render from."""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydub.utils import mediainfo

from src.domain.music_type import OneLyricLine, SongSegment


@lru_cache(maxsize=512)
def _audio_duration_seconds(path: str, size: int, modified_ns: int) -> float:
    """Probe once per audio revision; decoding is a fallback for files without duration metadata."""
    _ = size, modified_ns
    try:
        duration = float(mediainfo(path).get("duration", ""))
        if math.isfinite(duration) and duration > 0:
            return duration
    except (TypeError, ValueError, OSError):
        pass

    from pydub import AudioSegment

    duration = len(AudioSegment.from_file(path)) / 1000
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError(f"Audio has no playable duration: {path}")
    return duration


def audio_duration_seconds(audio_path: str | Path) -> float:
    path = Path(audio_path)
    stat = path.stat()
    if stat.st_size == 0:
        raise ValueError(f"Audio file is empty: {path}")
    return _audio_duration_seconds(str(path.resolve()), stat.st_size, stat.st_mtime_ns)


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


def _valid_segment(raw: Any, audio_duration: float) -> SongSegment | None:
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
    if end > audio_duration + 0.01:
        return None
    normalized_lyrics = _valid_lyrics(lyrics)
    if normalized_lyrics is None:
        return None
    return SongSegment(description=description, start_time=start, end_time=end, lyrics=normalized_lyrics)


def playable_segments(raw_segments: Any, audio_path: str | Path) -> list[SongSegment]:
    """Return only segments with a name, valid times, valid lyrics, and audio in range."""
    if not isinstance(raw_segments, list) or not raw_segments:
        return []
    try:
        duration = audio_duration_seconds(audio_path)
    except Exception:
        # Corrupt or unsupported media must not enter the singable catalog.
        return []

    valid: list[SongSegment] = []
    descriptions: set[str] = set()
    for raw in raw_segments:
        segment = _valid_segment(raw, duration)
        if segment is None or segment.description in descriptions:
            continue
        descriptions.add(segment.description)
        valid.append(segment)
    return valid
