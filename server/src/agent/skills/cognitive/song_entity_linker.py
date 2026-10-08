from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import List

from flashtext import KeywordProcessor


class SongEntityLinker:
    """Fast song-name and lyric entity linker.

    This capability produces verified song cues for Agent text preprocessing.
    """

    def __init__(
        self,
        config: dict,
        songname_file: str | None = None,
        lyric_file: str | None = None,
        *,
        song_names: Iterable[str] = (),
    ):
        self.config = config
        self.songname_retriver = KeywordProcessor()
        self.lyric_retriver = KeywordProcessor()
        configured_songname_file = config.get("songname_file")
        configured_lyric_file = config.get("lyric_file")
        self.songname_file = (
            songname_file
            or configured_songname_file
            or str(Path(__file__).resolve().parents[3] / "res" / "knowledge" / "song_name_keywords.txt")
        )
        self.lyric_file = (
            lyric_file
            or configured_lyric_file
            or str(Path(__file__).resolve().parents[3] / "res" / "knowledge" / "song_lyric_keywords.txt")
        )
        self._load_keywords_from_file()
        for song_name in song_names:
            if isinstance(song_name, str) and song_name.strip():
                self.songname_retriver.add_keyword(song_name.strip())

        self.trigger_verbs = {"听", "唱", "点", "循环", "安利", "写", "作曲", "调教", "歌"}

    def extract_and_verify(self, user_input: str | None) -> List[str]:
        if not user_input:
            return []

        songnames_found = self.songname_retriver.extract_keywords(user_input)
        lyrics_found = self.lyric_retriver.extract_keywords(user_input)

        triggered = any(verb in user_input for verb in self.trigger_verbs)
        if not triggered:
            songnames_found = []

        # 带歌曲触发词的书名号内容是比词库子串更强的候选。最终能否演唱仍由
        # SingingBackend 校验；这里保留完整标题，避免“《死别》”被链接成“《别》”。
        quoted_titles = (
            [title.strip() for title in re.findall(r"《([^》]+)》", user_input) if title.strip()]
            if triggered
            else []
        )

        results = []
        seen_songs = set()
        for song in (*quoted_titles, *songnames_found):
            if song in seen_songs or any(song != title and song in title for title in quoted_titles):
                continue
            seen_songs.add(song)
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
