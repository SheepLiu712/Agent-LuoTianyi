from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, List, Optional

from src.agent.main_chat import ContextType as ResponseLineType
from src.agent.main_chat import OneResponseLine, OneSentenceChat, SongSegmentChat
from src.agent.chat.chat_events import ChatInputEvent, ChatInputEventType
from src.domain.conversation_type import ConversationItem
from src.utils.enum_type import ContextType, ConversationSource
from src.utils.logger import get_logger
from src.system.conversation.conversation_manager import ConversationManager

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from src.system.database.memory_storage import MemoryStorage


class ConversationService:
    """Owns application-level conversation persistence and history queries."""

    def __init__(
        self,
        conversation_manager: ConversationManager,
        sql_session_factory,
        redis_client: "MemoryStorage",
    ) -> None:
        self.conversation_manager = conversation_manager
        self.sql_session_factory = sql_session_factory
        self.redis_client = redis_client
        self.logger = get_logger("ConversationService")

    def open_sql_session(self) -> "Session":
        return self.sql_session_factory()

    async def persist_user_event(self, user_id: Optional[str], event: ChatInputEvent) -> Optional[str]:
        if user_id is None:
            self.logger.warning("user_id is None in persist_user_event, skipping")
            return None
        if event.event_type not in {ChatInputEventType.USER_TEXT, ChatInputEventType.USER_IMAGE}:
            self.logger.warning(f"Unsupported event type {event.event_type} in persist_user_event, skipping")
            return None

        if event.payload and event.payload.get("is_proactive"):
            self.logger.info(f"Skipping DB save for proactive message: {event.text[:50]}...")
            return None

        payload = event.payload or {}
        content = event.text
        if event.event_type == ChatInputEventType.USER_IMAGE:
            conversation_type = ContextType.IMAGE
            data = {
                "image_client_path": payload.get("image_client_path"),
                "image_server_path": payload.get("image_server_path"),
                "mime_type": payload.get("mime_type"),
                "terms": payload.get("terms", []),
            }
        else:
            conversation_type = ContextType.TEXT
            data = {"terms": payload.get("terms", [])}

        db = self.open_sql_session()
        try:
            return await self.conversation_manager.add_conversation(
                db=db,
                redis=self.redis_client,
                user_id=user_id,
                source=ConversationSource.USER,
                content=content,
                type=conversation_type,
                data=data,
            )
        finally:
            db.close()

    async def persist_agent_replies(
        self,
        user_id: str,
        reply_items: List[OneResponseLine],
    ) -> List[Optional[str]]:
        if not user_id:
            return []

        conversation_items: list[ConversationItem] = []
        persisted_indices: list[int] = []
        now = time.strftime("%Y-%m-%d %H:%M:%S")

        for index, item in enumerate(reply_items):
            if isinstance(item, OneSentenceChat):
                text = item.get_content()
                if not text:
                    continue
                conversation_items.append(
                    ConversationItem(
                        uuid="",
                        timestamp=now,
                        source=ConversationSource.AGENT.value,
                        type=ContextType.TEXT.value,
                        content=text,
                        data=None,
                    )
                )
                persisted_indices.append(index)
            elif isinstance(item, SongSegmentChat):
                song_name = item.song or None
                if not song_name:
                    continue
                lyrics = item.lyrics
                conversation_items.append(
                    ConversationItem(
                        uuid="",
                        timestamp=now,
                        source=ConversationSource.AGENT.value,
                        type=ContextType.SING.value,
                        content=f"（唱了《{song_name}》）\n{lyrics}",
                        data={"song": song_name, "segment": item.segment},
                    )
                )
                persisted_indices.append(index)
            elif getattr(item, "type", None) not in {ResponseLineType.TEXT, ResponseLineType.SING}:
                self.logger.warning(f"Unsupported agent reply line type for persistence: {getattr(item, 'type', None)}")

        if not conversation_items:
            return [None] * len(reply_items)

        db = self.open_sql_session()
        try:
            uuid_list = await self.conversation_manager.add_conversation_list_to_db(
                db=db,
                redis=self.redis_client,
                user_id=user_id,
                conversation_list=conversation_items,
                commit=True,
            )
        finally:
            db.close()

        result: list[Optional[str]] = [None] * len(reply_items)
        for index, uuid in zip(persisted_indices, uuid_list):
            result[index] = uuid
        return result

    async def get_context(
        self,
        user_id: str,
        ret_type: str = "str",
        ts_type: str = "elapsed",
    ) -> str | dict[str, Any]:
        db = self.open_sql_session()
        try:
            return await self.conversation_manager.get_context(
                db, self.redis_client, user_id, ret_type=ret_type, ts_type=ts_type
            )
        finally:
            db.close()

    async def handle_history_request(self, user_id: str, count: int, end_index: int) -> dict[str, Any]:
        db = self.open_sql_session()
        try:
            total_count = await self.conversation_manager.get_total_conversation_count(db, user_id)
            if end_index == -1 or end_index > total_count:
                end_index = total_count

            start_index = max(0, end_index - count)
            if start_index >= end_index:
                return {"history": [], "start_index": 0}

            history_items = await self.conversation_manager.get_history(db, user_id, start_index, end_index)
            ret: dict[str, Any] = {"history": [], "start_index": start_index}
            for item in history_items:
                content = item.content
                if item.type == ContextType.IMAGE.value and item.data:
                    content = item.data.get("image_client_path")
                ret["history"].append(
                    {
                        "uuid": item.uuid,
                        "content": content,
                        "source": item.source,
                        "timestamp": item.timestamp,
                        "type": item.type,
                    }
                )
            return ret
        finally:
            db.close()

    async def update_context_if_needed(self, user_id: str) -> str | dict[str, Any] | None:
        db = self.open_sql_session()
        try:
            if not await self.conversation_manager.is_conversation_too_long(db, user_id):
                return None
            context = await self.conversation_manager.get_context(
                db, self.redis_client, user_id, ret_type="json", ts_type="date"
            )
            await self.conversation_manager._update_context(
                db, self.redis_client, user_id, context, commit=True
            )
            return context
        finally:
            db.close()
