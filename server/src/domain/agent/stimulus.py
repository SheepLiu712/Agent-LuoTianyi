from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class PersistPolicy(str, Enum):
    """Controls whether raw stimulus content enters conversation or memory evidence."""

    NONE = "none"
    EPHEMERAL_ONLY = "ephemeral_only"
    CONVERSATION_ONLY = "conversation_only"
    CONVERSATION_AND_MEMORY_CANDIDATE = "conversation_and_memory_candidate"


class StimulusKind(str, Enum):
    """Stable discriminator for the implemented stimulus variants."""

    TEXT_MESSAGE = "text_message"


class StimulusSource(str, Enum):
    """Supplier-independent semantic owner of a stimulus fact."""

    USER = "user"


@dataclass(frozen=True, slots=True)
class TextMessage:
    """An immutable, complete user text message submitted to an Agent.

    Identity, schema, occurrence time, semantic source, target characters,
    optional user, persistence policy, lifetime, text, and client retry ID are
    retained exactly as supplied. ``kind`` is always ``TEXT_MESSAGE`` and is
    not a constructor argument. This first Green slice implements only the
    approved legal construction; invalid combinations remain a later TDD
    slice and are not validated here.
    """

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
