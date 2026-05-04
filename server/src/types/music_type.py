from dataclasses import dataclass, field
from typing import List


@dataclass
class WishEntry:
    """A song a user wanted but the system couldn't sing at the time."""
    safe_name: str
    request_count: int = 1
    first_requested: str = ""       # ISO date, e.g. "2026-05-05"
    last_attempt: str = ""
    attempt_count: int = 0
    status: str = "pending"         # pending | awaiting_audio | learned | abandoned
    failure_reason: str = ""
    learned_date: str = ""


@dataclass
class OneLyricLine:
    duration: float  # in seconds
    content: str

@dataclass
class SongSegment:
    description: str
    start_time: float  # in seconds
    end_time: float    # in seconds
    lyrics: List[OneLyricLine]

@dataclass
class SongMetadata:
    title: str
    description: str
    song_path: str
    lrc_path: str
    lrc_offset: float  # in seconds
    segments: list[SongSegment]