"""Wire-level WebSocket event and payload types."""

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

_BUSINESS_INPUT_EVENTS = frozenset(
    {
        "user_text",
        "user_message",
        "message",
        "chat_message",
        "chat",
        "user_typing",
        "user_image",
        "user_voice",
        "user_voice_recording_started",
        "user_voice_recording_cancelled",
        "user_touch",
        "user_image_selecting",
        "user_image_selecting_cancel",
    }
)


class _ChatResponse(BaseModel):
    uuid: str
    text: str
    audio: str | None = None
    expression: str | None = None
    is_final_package: bool = True
    audio_error: bool | None = None
    error_code: str | None = None
    display_in_chat: bool = True
    is_ephemeral: bool = False
    packet_sequence: int | None = None


@dataclass
class _WSMessage:
    event_type: str
    payload: dict[str, Any]
    client_msg_id: str | None = None
    ts: int | None = None
    reply_to: str | None = None
    raw_event: dict[str, Any] | None = None
    raw_text: str | None = None
