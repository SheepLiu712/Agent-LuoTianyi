from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping
from uuid import uuid4


class MemoryType(str, Enum):
    USER_PROFILE = "user_profile"
    USER_FACT = "user_fact"
    INTERACTION_EVENT = "interaction_event"
    AGENT_LIFE = "agent_life"
    WORLD_EVENT = "world_event"
    DIARY_SOURCE = "diary_source"
    PUBLIC_DIARY = "public_diary"
    SONG_KNOWLEDGE = "song_knowledge"
    CHARACTER_SETTING = "character_setting"


class MemoryVisibility(str, Enum):
    PRIVATE = "private"
    CHARACTER_PRIVATE = "character_private"
    PUBLIC = "public"


@dataclass(frozen=True)
class MemoryRecord:
    """Canonical memory entity.

    Vector embeddings and graph edges should point back to this record instead
    of becoming the source of truth.
    """

    owner_character_id: str
    memory_type: MemoryType
    visibility: MemoryVisibility
    source: str
    content: str
    subject_user_id: str | None = None
    summary: str | None = None
    importance: float = 0.5
    confidence: float = 1.0
    emotional_valence: float | None = None
    happened_at: datetime | None = None
    created_at: datetime = field(default_factory=datetime.now)
    last_accessed_at: datetime | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid4()))
