from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping
from uuid import uuid4


class SourceChannel(str, Enum):
    WEBSOCKET = "websocket"
    HTTP = "http"
    PHONE = "phone"
    DEVICE = "device"
    WORLD = "world"
    SYSTEM = "system"


class StimulusModality(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    VOICE = "voice"
    TOUCH = "touch"
    TYPING = "typing"
    IMAGE_SELECTING = "image_selecting"
    IMAGE_SELECTING_CANCEL = "image_selecting_cancel"
    WORLD_EVENT = "world_event"
    SYSTEM_EVENT = "system_event"
    UNKNOWN = "unknown"


class PersistPolicy(str, Enum):
    NONE = "none"
    EPHEMERAL_ONLY = "ephemeral_only"
    CONVERSATION_ONLY = "conversation_only"
    CONVERSATION_AND_MEMORY_CANDIDATE = "conversation_and_memory_candidate"


@dataclass(frozen=True)
class Stimulus:
    """A normalized input stimulus for the future agent runtime.

    The legacy chat pipeline still consumes ChatInputEvent. This object gives
    new channels a common shape before they are adapted into legacy events.
    """

    source_channel: SourceChannel
    modality: StimulusModality
    payload: Mapping[str, Any] = field(default_factory=dict)
    text: str | None = None
    sender_user_id: str | None = None
    target_character_ids: tuple[str, ...] = ("luotianyi",)
    raw_event_type: str | None = None
    client_msg_id: str | None = None
    timestamp_ms: int | None = None
    persist_policy: PersistPolicy = PersistPolicy.NONE
    ephemeral: bool = False
    stimulus_id: str = field(default_factory=lambda: str(uuid4()))

    def targets_character(self, character_id: str) -> bool:
        return character_id in self.target_character_ids

    def should_persist_conversation(self) -> bool:
        return self.persist_policy in {
            PersistPolicy.CONVERSATION_ONLY,
            PersistPolicy.CONVERSATION_AND_MEMORY_CANDIDATE,
        }

    def can_be_memory_candidate(self) -> bool:
        return self.persist_policy == PersistPolicy.CONVERSATION_AND_MEMORY_CANDIDATE
