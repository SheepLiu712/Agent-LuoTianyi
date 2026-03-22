
from pydantic import BaseModel
class ChatRequest(BaseModel):
    text: str
    username: str
    token: str

class HistoryRequest(BaseModel):
    username: str
    token: str
    count: int = 10
    end_index: int = -1

class ChatResponse(BaseModel):
    uuid: str
    text: str
    audio: str | None = None
    expression: str | None = None
    is_final_package: bool = True

class LoginRequest(BaseModel):
    username: str
    password: str
    request_token: bool = False

class RegisterRequest(BaseModel):
    username: str
    password: str
    invite_code: str

class AutoLoginRequest(BaseModel):
    username: str
    token: str

from fastapi import Form, File, UploadFile
class PictureChatRequest:
    def __init__(
        self,
        username: str = Form(...),
        token: str = Form(...),
        image: UploadFile = File(...),
        image_client_path: str = Form(None)
    ):
        self.username = username
        self.token = token
        self.image = image
        self.image_client_path = image_client_path


class ImageRequest(BaseModel):
    username: str
    token: str
    uuid: str
    image_client_path: str = None


#### WebSocket Event Types
from enum import Enum
from dataclasses import dataclass
from typing import Dict


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


    HB_PING = "hb_ping"
    HB_PONG = "hb_pong"

@dataclass
class WSMessage:
    event_type: str
    payload: Dict
    client_msg_id: str | None = None
    ts: int | None = None
    reply_to: str | None = None
