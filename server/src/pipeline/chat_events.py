from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional


class ChatInputEventType(str, Enum):
    USER_TEXT = "user_text"
    USER_IMAGE = "user_image"
    USER_TYPING = "user_typing"
    USER_TOUCH = "user_touch"
    USER_IMAGE_SELECTING = "user_image_selecting"
    USER_IMAGE_SELECTING_CANCEL = "user_image_selecting_cancel"
    SYSTEM_EVENT = "system_event" # 预留的系统事件类型，当前未使用


@dataclass
class ChatInputEvent:
    """chat_stream 的统一输入事件，独立于 WebSocket 原始协议。"""

    event_type: ChatInputEventType
    text: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None
    client_msg_id: Optional[str] = None
    ts: Optional[int] = None
