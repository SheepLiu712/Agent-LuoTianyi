from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class ChatInputEventType(str, Enum):
    USER_TEXT = "user_text"
    USER_IMAGE = "user_image"
    USER_TYPING = "user_typing"
    USER_TOUCH = "user_touch"
    USER_IMAGE_SELECTING = "user_image_selecting"
    USER_IMAGE_SELECTING_CANCEL = "user_image_selecting_cancel"
    SYSTEM_EVENT = "system_event"


@dataclass
class ChatInputEvent:
    """Unified chat-stream input event independent of WebSocket framing."""

    event_type: ChatInputEventType
    text: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None
    client_msg_id: Optional[str] = None
    ts: Optional[int] = None


@dataclass
class UnreadMessage:
    message_id: str
    message_type: str
    content: str
    target_character_ids: tuple[str, ...] = ("luotianyi",)
    terms: List[str] | None = None


@dataclass
class UnreadMessageSnapshot:
    messages: List[UnreadMessage]
    version: int


@dataclass
class ExtractedTopic:
    topic_id: str
    source_messages: list[Any]
    topic_content: str
    memory_attempts: list[str]
    fact_constraints: list[str]
    sing_attempts: list[str]
    target_character_ids: tuple[str, ...] = ("luotianyi",)
    source_event_type: str | None = None
    is_forced_from_incomplete: bool = False
