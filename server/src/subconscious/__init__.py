"""Subconscious layer.

This layer owns memory, jargon/entity recall, future attention candidates, and
state maintenance. Existing implementations are wrapped here first so callers
can migrate without a disruptive rewrite.
"""

from src.subconscious.music_knowledge.jargon import SongEntityLinker, extract_song_entities
from src.subconscious.memory import MemoryUpdateService, SubconsciousMemory
from src.subconscious.state import SubconsciousState

__all__ = [
    "MemoryUpdateService",
    "SongEntityLinker",
    "SubconsciousMemory",
    "SubconsciousState",
    "extract_song_entities",
]
