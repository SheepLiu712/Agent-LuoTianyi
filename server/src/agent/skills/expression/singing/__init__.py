"""Shared singing skill and its character-scoped implementation."""

from .backend import SingingBackend
from .emotion import SongEmotionTagger
from .manager import SingingManager
from .skill import EmptySongAudioError, SingingSkill
from .wishlist import WishlistManager

__all__ = [
    "EmptySongAudioError",
    "SingingBackend",
    "SingingManager",
    "SingingSkill",
    "SongEmotionTagger",
    "WishlistManager",
]
