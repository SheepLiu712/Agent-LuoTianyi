import asyncio
from typing import Any, List, TYPE_CHECKING
from src.domain.conversation_type import ConversationItem
from src.utils.enum_type import ContextType

if TYPE_CHECKING:
    from src.system.database import DatabaseManager


class UserConversationHelper:
    """
    用户对话助手类，提供与用户对话相关的辅助功能。
    """

    def __init__(self, database_manager: "DatabaseManager"):
        self.database_manager = database_manager

    async def handle_history_request(self, user_id: str, count: int, end_index: int) -> dict[str, Any]:
        total_count = await asyncio.to_thread(self.database_manager.get_total_conversation_count, user_id)
        if end_index == -1 or end_index > total_count:
            end_index = total_count

        start_index = max(0, end_index - count)
        if start_index >= end_index:
            return {"history": [], "start_index": 0}

        history_items: List[ConversationItem] = await asyncio.to_thread(
            self.database_manager.get_history_from_db,
            user_id,
            start_index,
            end_index,
        )
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
