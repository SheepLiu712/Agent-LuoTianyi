from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any, List

from src.subconscious.music_knowledge.knowledge_service import get_song_introduction, get_song_lyrics
from src.subconscious.music_knowledge.song_database import get_song_session, init_song_db


class SongKnowledgeMemory:
    """Memory-facing facade for song facts and lyrics knowledge."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self._init_song_database()

    async def search_song_facts_for_topic(self, constraints: List[str]) -> List[str]:
        if not constraints:
            return []

        db = get_song_session()
        try:
            dedup: List[str] = []
            seen = set()
            for raw in constraints:
                song_name = self._extract_song_name(raw)
                if not song_name:
                    continue

                intro = await asyncio.to_thread(get_song_introduction, db, song_name)
                lyrics = await asyncio.to_thread(get_song_lyrics, db, song_name)

                if intro:
                    text = f"《{song_name}》的介绍:\n{intro}"
                    if text not in seen:
                        seen.add(text)
                        dedup.append(text)

                if lyrics:
                    text = f"《{song_name}》的歌词:\n{lyrics}"
                    if text not in seen:
                        seen.add(text)
                        dedup.append(text)

            return dedup
        finally:
            db.close()

    def _init_song_database(self) -> None:
        song_db_config = self.config.get("song_database") or self._default_song_database_config()
        init_song_db(song_db_config)

    @staticmethod
    def _default_song_database_config() -> dict[str, str]:
        server_root = Path(__file__).resolve().parents[3]
        return {
            "db_folder": str(server_root / "res" / "knowledge"),
            "db_file": "knowledge_db.db",
        }

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
