import os
import sys

current_dir = os.getcwd()
if current_dir not in sys.path:
    sys.path.append(current_dir)

from src.agent.chat.chat_events import ChatInputEvent, ChatInputEventType
from src.system.conversation.conversation_service import ConversationService
from src.domain.conversation_type import ConversationItem
from src.utils.enum_type import ContextType, ConversationSource


class FakeDb:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class FakeConversationManager:
    def __init__(self):
        self.added = []

    async def add_conversation(self, db, redis, user_id, source, content, type, data):
        self.added.append(
            {
                "user_id": user_id,
                "source": source,
                "content": content,
                "type": type,
                "data": data,
            }
        )
        return "user-message-id"

    async def add_conversation_list_to_db(self, db, redis, user_id, conversation_list, commit=True):
        self.added.append({"user_id": user_id, "items": conversation_list, "commit": commit})
        return [f"reply-{index}" for index, _ in enumerate(conversation_list)]

    async def get_total_conversation_count(self, db, user_id):
        return 2

    async def get_history(self, db, user_id, start, end):
        return [
            ConversationItem(
                uuid="text-1",
                timestamp="2026-06-21 10:00:00",
                source=ConversationSource.USER.value,
                type=ContextType.TEXT.value,
                content="你好",
                data=None,
            ),
            ConversationItem(
                uuid="image-1",
                timestamp="2026-06-21 10:01:00",
                source=ConversationSource.USER.value,
                type=ContextType.IMAGE.value,
                content="图片描述",
                data={"image_client_path": "client/image.png"},
            ),
        ][start:end]


def test_conversation_service_persists_user_text_event():
    manager = FakeConversationManager()
    service = ConversationService(manager, sql_session_factory=FakeDb, redis_client="redis")
    event = ChatInputEvent(
        event_type=ChatInputEventType.USER_TEXT,
        text="你好呀",
        payload={"terms": ["《歌》是一首歌"]},
    )

    import asyncio

    uuid = asyncio.run(service.persist_user_event("user-1", event))

    assert uuid == "user-message-id"
    assert manager.added[0]["source"] == ConversationSource.USER
    assert manager.added[0]["type"] == ContextType.TEXT
    assert manager.added[0]["data"]["terms"] == ["《歌》是一首歌"]


def test_conversation_service_formats_history_for_user_interface():
    service = ConversationService(FakeConversationManager(), sql_session_factory=FakeDb, redis_client="redis")

    import asyncio

    result = asyncio.run(service.handle_history_request("user-1", count=2, end_index=-1))

    assert result["start_index"] == 0
    assert result["history"][0]["content"] == "你好"
    assert result["history"][1]["content"] == "client/image.png"
