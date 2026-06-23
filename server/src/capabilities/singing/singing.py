from __future__ import annotations

import re
from typing import Any, List, Optional, Tuple, Dict
from .singing_manager import SingingManager


class SingingCapability:
    """Action capability for choosing and rendering sing actions."""

    def __init__(self, config: Dict[str, Any]) -> None:
        self._config: Dict[str, Any] = config
        self.music_manager = SingingManager(config)

    def build_sing_plan(self, sing_attempts: List[str]) -> Tuple[Optional[str], Optional[str]]:
        if not sing_attempts:
            return None, None

        song_name = None
        for attempt in sing_attempts:
            candidate = (attempt or "").strip()
            if not candidate:
                continue
            if candidate == "random_song":
                pair = self.music_manager.pick_random_song_and_segment()
                return pair if pair else (None, None)

            song_name = self._extract_song_name(candidate)
            if not song_name:
                continue

            correct_song_name, segment = self.music_manager.pick_segment_for_song(song_name)
            if segment:
                return correct_song_name, segment
        if song_name:
            self.music_manager.add_wished_song(song_name)
        return song_name, None

    def sing(self, song_name: str, segment: str) -> Optional[bytes]:
        if not song_name or not segment:
            return None
        _, audio_bytes = self.music_manager.get_song_segment(song_name, segment)
        return audio_bytes

    def get_segment_lyrics(self, song_name: str, segment: str) -> str:
        return self.music_manager.get_segment_lyrics(song_name, segment)

    def _extract_song_name(self, text: str) -> str:
        content = (text or "").strip()
        if not content:
            return ""

        match = re.search(r"《([^》]+)》", content)
        if match:
            return match.group(1).strip()

        if "是一首歌" in content:
            return content.split("是一首歌", 1)[0].strip().strip("《》")

        return content.strip("\"'“”‘’《》")
