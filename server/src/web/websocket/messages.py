"""Wire-level WebSocket event and payload types."""

from dataclasses import dataclass
from enum import Enum
from typing import Any

from pydantic import BaseModel

BUSINESS_INPUT_EVENTS = frozenset(
    {"user_text", "user_message", "message", "chat_message", "chat", "user_typing", "user_image"}
)


class ChatResponse(BaseModel):
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


class WSEventType(str, Enum):
    SYSTEM_READY = "system_ready"
    AUTH_SUCCESS = "auth_success"
    AUTH_FAILURE = "auth_failure"
    SERVER_ERROR = "error"
    SERVER_ACK = "server_ack"
    AUTH_ERROR = "auth_error"
    AUTH_OK = "auth_ok"

    AGENT_STATE_CHANGED = "agent_state_changed"
    AGENT_MESSAGE = "agent_message"

    LLM_REQUEST = "llm_request"
    LLM_RESPONSE = "llm_response"

    USER_MESSAGE = "user_message"
    USER_IMAGE = "user_image"
    USER_TEXT = "user_text"
    USER_TYPING = "user_typing"
    USER_IMAGE_SELECTING = "user_image_selecting"
    USER_IMAGE_SELECTING_CANCEL = "user_image_selecting_cancel"
    USER_AUTH = "user_auth"
    USER_TOUCH = "user_touch"

    HB_PING = "hb_ping"
    HB_PONG = "hb_pong"
    DATE_DETECTED = "date_detected"


@dataclass
class WSMessage:
    event_type: str
    payload: dict[str, Any]
    client_msg_id: str | None = None
    ts: int | None = None
    reply_to: str | None = None
