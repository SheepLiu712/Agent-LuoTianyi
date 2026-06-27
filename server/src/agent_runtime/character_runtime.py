from __future__ import annotations

from dataclasses import dataclass

from src.agent.luotianyi_agent import LuoTianyiAgent
from src.domain import CharacterProfile
from src.subconscious.character_mind import CharacterSubconscious


@dataclass(frozen=True)
class CharacterRuntime:
    """Runtime pair for one character."""

    profile: CharacterProfile
    conscious: LuoTianyiAgent
    mind: CharacterSubconscious
