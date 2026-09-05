from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class PersistPolicy(str, Enum):
    NONE = "none"
    EPHEMERAL_ONLY = "ephemeral_only"
    CONVERSATION_ONLY = "conversation_only"
    CONVERSATION_AND_MEMORY_CANDIDATE = "conversation_and_memory_candidate"


class StimulusKind(str, Enum):
    TEXT_MESSAGE = "text_message"


class StimulusSource(str, Enum):
    USER = "user"


@dataclass(frozen=True, slots=True)
class TextMessage:
    stimulus_id: str
    schema_version: int
    occurred_at: datetime
    source: StimulusSource
    target_character_ids: tuple[str, ...]
    user_id: str | None
    persist_policy: PersistPolicy
    ephemeral: bool
    text: str
    client_msg_id: str
    kind: StimulusKind = field(default=StimulusKind.TEXT_MESSAGE, init=False)
