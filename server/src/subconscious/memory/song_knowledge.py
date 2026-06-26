from __future__ import annotations

from typing import Any, List


class SongKnowledgeMemory:
    """Memory-facing facade for song facts and lyrics knowledge."""

    def __init__(self, config: dict[str, Any], music_manager: Any) -> None:
        self.config = config
        self.music_manager = music_manager

    async def search_song_facts_for_topic(self, constraints: List[str]) -> List[str]:
        return await self.music_manager.search_song_facts_for_topic(constraints)
