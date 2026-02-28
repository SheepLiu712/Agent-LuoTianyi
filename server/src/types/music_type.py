from dataclasses import dataclass
from typing import List

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