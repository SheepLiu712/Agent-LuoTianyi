from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping
from enum import Enum


@dataclass(frozen=True)
class CharacterProfile:
    """Character-level configuration used by the runtime.

    Each character owns an independent memory namespace and future AgentState.
    """

    character_id: str
    display_name: str
    memory_namespace: str
    static_variables_file: str | None = None
    llm_tone_mapping_file: str | None = None
    persona_ref: str | None = None
    speaking_style_ref: str | None = None
    voice_profile: str | None = None
    live2d_profile: str | None = None
    default_target: bool = False
    enabled: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

# Character names
class CharacterName(Enum):
    LUOTIANYI = "luotianyi"
    YUEZHENGLING = "yuezhengling"
    YANHE = "yanhe"
