"""聊天 Adapter 内部使用的入站消息与下行内容契约。"""

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


class ChatResponse(BaseModel):
    """聊天下行消息内容，承载文字、音频、表情及终包标记。"""

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
class WSMessage:
    """解析后的聊天入站消息，保留原始报文以供大小和协议校验。"""

    event_type: str
    payload: dict[str, Any]
    client_msg_id: str | None = None
    ts: int | None = None
    reply_to: str | None = None
    raw_event: dict[str, Any] | None = None
    raw_text: str | None = None
