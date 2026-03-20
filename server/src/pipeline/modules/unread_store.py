from dataclasses import dataclass
from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from ..chat_events import ChatInputEvent, ChatInputEventType

@dataclass
class UnreadMessage:
    message_id: str
    message_type: str  # "text" or "image"
    content: str  # For text messages, this is the raw text; for images, this can be the caption or description



class UnreadStore:
    """
    UnreadStore用于存储用户的未读消息，提供添加、获取和清除未读消息的功能。
    添加之后，需要调用一次
    """

    def __init__(self, username: str, user_id: str):
        self.unread_messages: List[UnreadMessage] = []
        self.username: str = username
        self.user_id: str = user_id

    @staticmethod
    def trans_ChatInputEvent_to_UnreadMessage(event: ChatInputEvent) -> UnreadMessage:
        message_type = "text" if event.event_type == ChatInputEventType.USER_TEXT else "image"
        return UnreadMessage(
            message_id=event.client_msg_id,
            message_type=message_type,
            content=event.text,
        )

    def append(self, message: UnreadMessage):
        self.unread_messages.append(message)

    def snapshot(self) -> List[UnreadMessage]:
        return self.unread_messages.copy()
    
    def update_unread_messages(self, new_messages: List[UnreadMessage]):
        self.unread_messages = new_messages