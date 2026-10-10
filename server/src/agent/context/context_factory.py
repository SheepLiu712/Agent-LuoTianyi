"""创建交互上下文，不保存交互实例或管理其生命周期。"""

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING
from weakref import WeakValueDictionary

from ._lifecycle import _complete
from ._storage import _Storage
from .conversation_store import ConversationStore, EphemeralCallConversationStore
from .interaction_context import InteractionContext
from .models import ContextIdentity

if TYPE_CHECKING:
    from src.infrastructure.persistence.database.services.conversation_service import ConversationService


class ContextFactory:
    """角色的上下文创建依赖；创建结果由调用方持有并关闭。"""

    def __init__(
        self,
        *,
        character_id: str,
        database: "ConversationService",
        conversation_store_factory: Callable[[ContextIdentity], ConversationStore] | None = None,
    ) -> None:
        """绑定角色 character_id 与数据库 database，不保存已创建的 context。"""
        self._character_id = character_id
        self._database = database
        self._conversation_store_factory = conversation_store_factory
        self._user_locks: WeakValueDictionary[str | None, asyncio.Lock] = WeakValueDictionary()

    async def create(self, interaction_id: str, *, user_id: str | None) -> InteractionContext:
        """加载并返回新的 interaction_id 上下文；user_id 可为空，不查找或复用已有实例。

        调用方负责 close。创建被取消时，等待加载完成并关闭未交付的实例，再传播取消。
        """
        identity = ContextIdentity(self._character_id, interaction_id, user_id)
        return await self._create(identity)

    async def create_call(
        self,
        interaction_id: str,
        *,
        user_id: str,
        requested_at: datetime,
    ) -> InteractionContext:
        """创建只以内存 Store 工作的通话上下文；requested_at 使用服务器本地 naive 时间。"""
        if not isinstance(user_id, str) or not user_id.strip():
            raise ValueError("通话上下文需要非空 user_id")
        if not isinstance(requested_at, datetime) or requested_at.tzinfo is not None:
            raise ValueError("requested_at 应为不带时区的服务器本地时间")
        identity = ContextIdentity(self._character_id, interaction_id, user_id)

        def call_store() -> ConversationStore:
            seed = _Storage(self._database, identity).load_call_conversation_seed(requested_at=requested_at)
            return EphemeralCallConversationStore(seed)

        return await self._create(identity, store_factory=call_store)

    async def _create(
        self,
        identity: ContextIdentity,
        *,
        store_factory: Callable[[], ConversationStore] | None = None,
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
                    store = (
                        store_factory()
                        if store_factory is not None
                        else self._conversation_store_factory(identity) if self._conversation_store_factory else None
                    )
                    try:
                        return InteractionContext(identity=identity, database=self._database, conversation_store=store)
                    except BaseException:
                        if store is not None:
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
