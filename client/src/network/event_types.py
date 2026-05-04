import json
import time
import uuid
from typing import Any, Dict
from enum import Enum
from dataclasses import dataclass

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

    USER_MESSAGE = "user_message"
    USER_IMAGE = "user_image"
    USER_TEXT = "user_text"
    USER_TYPING = "user_typing"
    USER_AUTH = "user_auth"
    USER_TOUCH = "user_touch"


    HB_PING = "hb_ping"
    HB_PONG = "hb_pong"

@dataclass
class WSMessage:
    event_type: WSEventType
    payload: Dict
    client_msg_id: str | None = None
    ts: int | None = None
    reply_to: str | None = None

    def __dict__(self):
        return {
            "type": self.event_type.value,
            "payload": self.payload,
            "client_msg_id": self.client_msg_id,
            "ts": self.ts,
            "reply_to": self.reply_to,
        }

@dataclass
class AgentMessage:
    text: str | None
    audio: str | None
    expression: str | None
    is_final_package: bool
    uuid: str | None
    reply_to: str | None

@dataclass
class AgentStateMessage:
    state: str
    reply_to: str | None

@dataclass
class ErrorMessage:
    code: str
    message: str
    reply_to: str | None


def build_event(event_type: WSEventType, payload: Dict[str, Any] | None = None, client_msg_id: str | None = None) -> WSMessage:
    return WSMessage(
        event_type=event_type,
        payload=payload or {},
        client_msg_id=client_msg_id or f"c-{uuid.uuid4().hex[:12]}",
        ts=int(time.time() * 1000),
    )
    


def parse_server_message(raw: str) -> WSMessage | None:
    try:
        msg = json.loads(raw)
    except Exception:
        return None
    if not isinstance(msg, dict):
        return None
    
    event_type = msg.get("type")
    for known_type in WSEventType:
        if event_type == known_type.value:
            event_type = known_type
            break
    else:
        event_type = None

    return WSMessage(
        event_type=event_type,
        payload=msg.get("payload", {}),
        client_msg_id=msg.get("client_msg_id"),
        ts=msg.get("ts"),
        reply_to=msg.get("reply_to"),
    )


def normalize_agent_message(message: WSMessage) -> AgentMessage:
    payload = message.payload
    return AgentMessage(
        text=payload.get("text"),
        audio=payload.get("audio"),
        expression=payload.get("expression"),
        is_final_package=bool(payload.get("is_final_package", True)),
        uuid=payload.get("uuid"),
        reply_to=message.reply_to,
    )


def normalize_error_message(message: WSMessage) -> ErrorMessage:
    payload = message.payload
    code = payload.get("code", "UNKNOWN")
    text = payload.get("message", "server error")
    return ErrorMessage(
        code=code,
        message=text,
        reply_to=message.reply_to,
    )
