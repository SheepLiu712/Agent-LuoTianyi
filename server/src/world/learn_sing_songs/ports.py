"""Consumer-owned ports for the world song-learning workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class SingingManagerPort(Protocol):
    """Character-scoped song library required by the learning workflow."""

    character_name: str
    resource_path: str | Path
    wishlist: Any


class SingingBackendPort(Protocol):
    """Narrow bridge from world jobs to the Agent-owned singing capability."""

    singing_manager: dict[str, SingingManagerPort]

    def reload_songs(self, character_id: str) -> None: ...

    async def tag_song_emotions(self, character_id: str, song_name: str) -> Any: ...
