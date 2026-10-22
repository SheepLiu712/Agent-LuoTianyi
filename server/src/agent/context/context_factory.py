"""创建交互上下文，不保存交互实例或管理其生命周期。"""

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING
from weakref import WeakValueDictionary

from ._conversation_store import ConversationStore, DatabaseConversationStore, EphemeralCallConversationStore
from ._lifecycle import _complete
from ._storage import _Storage
from .interaction_context import InteractionContext
from .models import ContextIdentity, ConversationMode

if TYPE_CHECKING:
    from src.infrastructure.persistence.database.services.conversation_service import ConversationService


class ContextFactory:
    """角色的上下文创建依赖；创建结果由调用方持有并关闭。"""

    def __init__(
        self,
        *,
        character_id: str,
        database: "ConversationService",
    ) -> None:
        """绑定角色 character_id 与数据库 database，不保存已创建的 context。"""
        self._character_id = character_id
        self._database = database
        self._user_locks: WeakValueDictionary[str | None, asyncio.Lock] = WeakValueDictionary()

    async def create(
        self,
        interaction_id: str,
        *,
        user_id: str | None,
        mode: ConversationMode,
        requested_at: datetime | None = None,
    ) -> InteractionContext:
        """按显式模式加载完整上下文；每次创建独占实例，调用方负责 close。

        CALL 要求非空用户和服务器本地 naive requested_at，seed 由内部读取；
        CHAT 不接收 requested_at，保留持久聊天及无用户世界交互的行为。
        取消时等待加载完成，关闭未交付实例后再传播取消。
        """
        if not isinstance(mode, ConversationMode):
            raise ValueError("mode 应为 ConversationMode.CHAT 或 ConversationMode.CALL")
        if mode is ConversationMode.CALL:
            if not isinstance(user_id, str) or not user_id.strip():
                raise ValueError("通话上下文需要非空 user_id")
            if not isinstance(requested_at, datetime) or requested_at.tzinfo is not None:
                raise ValueError("requested_at 应为不带时区的服务器本地时间")
        elif requested_at is not None:
            raise ValueError("CHAT 上下文不接收 requested_at")
        identity = ContextIdentity(self._character_id, interaction_id, user_id)

        def build_store() -> ConversationStore:
            if mode is ConversationMode.CALL:
                seed = _Storage(self._database, identity).load_call_conversation_seed(requested_at=requested_at)
                return EphemeralCallConversationStore(seed)
            return DatabaseConversationStore(self._database, identity)

        return await self._create(identity, store_factory=build_store)

    async def _create(
        self,
        identity: ContextIdentity,
        *,
        store_factory: Callable[[], ConversationStore],
    ) -> InteractionContext:
        """在同用户锁内完成全部读取；取消时关闭已经创建但尚未交付的上下文。"""
        user_id = identity.user_id
        lock = self._user_locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            self._user_locks[user_id] = lock
        created: list[InteractionContext] = []

        async def load() -> InteractionContext:
            async with lock:

                def build() -> InteractionContext:
                    store = store_factory()
                    try:
                        return InteractionContext(identity=identity, database=self._database, _conversation_store=store)
                    except BaseException:
                        try:
                            store.close()
                        except BaseException:
                            pass
                        raise

                context = await asyncio.to_thread(build)
                context._state.lock = lock
                created.append(context)
                return context

        try:
            return await _complete(load())
        except asyncio.CancelledError:
            if created:
                await created[0].close()
            raise
