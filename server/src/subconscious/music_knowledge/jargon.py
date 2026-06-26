from __future__ import annotations

from pathlib import Path
from typing import List

from flashtext import KeywordProcessor


class SongEntityLinker:
    """Fast song-name and lyric entity linker.

    This belongs to the subconscious layer because it produces recall cues for
    later planning/reply generation rather than a surface-level response.
    """

    def __init__(self, config: dict, songname_file: str | None = None, lyric_file: str | None = None):
        self.config = config
        self.songname_retriver = KeywordProcessor()
        self.lyric_retriver = KeywordProcessor()
        configured_songname_file = config.get("songname_file")
        configured_lyric_file = config.get("lyric_file")
        self.songname_file = songname_file or configured_songname_file or str(
            Path(__file__).resolve().parents[2] / "res" / "knowledge" / "song_name_keywords.txt"
        )
        self.lyric_file = lyric_file or configured_lyric_file or str(
            Path(__file__).resolve().parents[2] / "res" / "knowledge" / "song_lyric_keywords.txt"
        )
        self._load_keywords_from_file()

        self.trigger_verbs = {"听", "唱", "点", "循环", "安利", "写", "作曲", "调教", "歌"}

    def extract_and_verify(self, user_input: str | None) -> List[str]:
        if not user_input:
            return []

        songnames_found = self.songname_retriver.extract_keywords(user_input)
        lyrics_found = self.lyric_retriver.extract_keywords(user_input)

        triggered = any(verb in user_input for verb in self.trigger_verbs)
        if not triggered:
            songnames_found = []

        results = []
        for song in songnames_found:
            results.append(f"《{song}》是一首歌")
        for lyric in lyrics_found:
            results.append(f"{lyric}")

        return results

    def _load_keywords_from_file(self) -> None:
        songname_path = Path(self.songname_file)
        lyric_path = Path(self.lyric_file)

        if not songname_path.exists() or not lyric_path.exists():
            return

        self.songname_retriver.add_keyword_from_file(str(songname_path))
        self.lyric_retriver.add_keyword_from_file(str(lyric_path))


song_entity_linker = SongEntityLinker({})


def extract_song_entities(user_input: str | None) -> List[str]:
    return song_entity_linker.extract_and_verify(user_input)
