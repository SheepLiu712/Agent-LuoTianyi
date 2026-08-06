from typing import List, TYPE_CHECKING
from src.domain.chat import ChatInputEvent, ChatInputEventType, UnreadMessage, UnreadMessageSnapshot
from src.utils.logger import get_logger
import asyncio
if TYPE_CHECKING:
    pass

class UnreadStore:
    """
    UnreadStore用于存储用户的未读消息，提供添加、获取和清除未读消息的功能。
    添加之后，需要调用一次
    """
    def __init__(self, config: dict, username: str, user_id: str):
        self.config = config
        self.logger = get_logger(f"{username}UnreadStore")
        self.maxsize = max(1, int(config.get("maxsize", 128)))
        self.unread_messages: List[UnreadMessage] = []
        self.username: str = username
        self.user_id: str = user_id
        self._snapshot_version: int = 0  # 用于跟踪消息版本，确保一致性
        self._snapshot: UnreadMessageSnapshot | None = None
        self._message_lock = asyncio.Lock()  # 用于保护unread_messages的并发访问
        self._capacity_changed = asyncio.Condition(self._message_lock)
        # A snapshot still owns its messages until update_unread_message commits.
        self._occupied_count = 0

    @staticmethod
    def trans_ChatInputEvent_to_UnreadMessage(event: ChatInputEvent) -> UnreadMessage:
        if event.event_type == ChatInputEventType.USER_IMAGE:
            message_type = "image"
        elif event.event_type == ChatInputEventType.USER_TOUCH:
            message_type = "touch"
        else:
            message_type = "text"
        return UnreadMessage(
            message_id=event.client_msg_id,
            message_type=message_type,
            content=event.text or "",
            terms=event.payload.get("terms", []) if event.payload else [],
            target_character_ids=tuple(event.payload.get("target_character_ids") or ("luotianyi",)) if event.payload else ("luotianyi",),
        )

    async def append(self, message: UnreadMessage):
        async with self._capacity_changed:
            while self._occupied_count >= self.maxsize:
                await self._capacity_changed.wait()
            self.unread_messages.append(message)
            self._occupied_count += 1

    async def snapshot(self) -> UnreadMessageSnapshot:
        async with self._message_lock:
            if self._snapshot is not None:
                self.logger.error("在snapshot被销毁之前不应该重新建立snapshot，可能存在并发问题")
                return self._snapshot
            self._snapshot_version += 1
            self._snapshot = UnreadMessageSnapshot(messages=self.unread_messages.copy(), version=self._snapshot_version)
            self.unread_messages.clear()  # 清空当前未读消息列表
            return self._snapshot

    async def update_unread_message(self, snapshot: UnreadMessageSnapshot, remained_messages: List[UnreadMessage]):
        async with self._capacity_changed:
            if self._snapshot is None or snapshot.version != self._snapshot.version:
                self.logger.error("更新未读消息失败，版本不匹配，可能存在并发问题")
                return
            if len(remained_messages) > len(snapshot.messages):
                raise ValueError("remained_messages cannot exceed the active snapshot")

            released = len(snapshot.messages) - len(remained_messages)
            self._snapshot = None  # 销毁当前snapshot
            self.unread_messages = remained_messages + self.unread_messages  # 将未处理的消息重新加入未读消息列表
            self._occupied_count -= released
            if released:
                self._capacity_changed.notify_all()

    async def has_unread(self) -> bool:
        async with self._message_lock:
            return len(self.unread_messages) > 0

    async def pending_count(self) -> int:
        """Return all capacity-owned messages, including the active snapshot."""
        async with self._message_lock:
            return self._occupied_count
        
    async def clear(self):
        async with self._capacity_changed:
            self.unread_messages.clear()
            self._snapshot = None
            self._occupied_count = 0
            self._capacity_changed.notify_all()
