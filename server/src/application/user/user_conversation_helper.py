import asyncio
from typing import TYPE_CHECKING, Any, List

from src.domain.agent import MediaRef
from src.domain.conversation_type import ConversationItem
from src.infrastructure.media import MediaResolutionError

if TYPE_CHECKING:
    from src.infrastructure.persistence.database import DatabaseManager


class UserConversationHelper:
    """
    用户对话助手类，提供与用户对话相关的辅助功能。
    """

    def __init__(self, database_manager: "DatabaseManager", media_resolver=None):
        self.database_manager = database_manager
        self.media_resolver = media_resolver

    async def _audio_available(self, user_id: str, item: ConversationItem) -> bool:
        media_id = (item.data or {}).get("media_id")
        if not isinstance(media_id, str) or not media_id.strip() or self.media_resolver is None:
            return False
        try:
            await asyncio.to_thread(
                self.media_resolver.resolve,
                MediaRef(media_id=media_id),
                owner_user_id=user_id,
                expected_kind="audio",
            )
        except (MediaResolutionError, OSError, ValueError):
            return False
        return True

    async def handle_history_request(self, user_id: str, count: int, end_index: int) -> dict[str, Any]:
        total_count = await asyncio.to_thread(
            self.database_manager.conversation_service.get_total_conversation_count,
            user_id,
        )
        if end_index == -1 or end_index > total_count:
            end_index = total_count

        start_index = max(0, end_index - count)
        if start_index >= end_index:
            return {"history": [], "start_index": 0}

        history_items: List[ConversationItem] = await asyncio.to_thread(
            self.database_manager.conversation_service.get_history_from_db,
            user_id,
            start_index,
            end_index,
        )
        ret: dict[str, Any] = {"history": [], "start_index": start_index}
        for item in history_items:
            content = item.content
            extra = {}
            if item.type == "image":
                # 图片理解文本只属于 Agent 上下文；用户历史只暴露图片缓存位置。
                content = (item.data or {}).get("image_client_path") or ""
            elif item.type == "audio":
                content = "[语音消息]"
                duration_ms = (item.data or {}).get("duration_ms")
                extra = {
                    "duration_ms": duration_ms if type(duration_ms) is int else 0,
                    "audio_available": await self._audio_available(user_id, item),
                }
            ret["history"].append(
                {
                    "uuid": item.uuid,
                    "content": content,
                    "source": item.source,
                    "timestamp": item.timestamp,
                    "type": item.type,
                    **extra,
                }
            )
        return ret
