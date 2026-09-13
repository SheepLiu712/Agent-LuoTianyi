"""创建交互上下文，不保存交互实例或管理其生命周期。"""
import asyncio
from weakref import WeakValueDictionary
from typing import TYPE_CHECKING

from ._lifecycle import _complete
from .interaction_context import InteractionContext
from .models import ContextIdentity

if TYPE_CHECKING:
    from src.system.database.services.conversation_service import ConversationService


class ContextFactory:
    """角色的上下文创建依赖；创建结果由调用方持有并关闭。"""

    def __init__(self, *, character_id: str, database: "ConversationService") -> None:
        """绑定角色 character_id 与数据库 database，不保存已创建的 context。"""
        self._character_id = character_id
        self._database = database
        self._user_locks: WeakValueDictionary[str | None, asyncio.Lock] = WeakValueDictionary()

    async def create(self, interaction_id: str, *, user_id: str | None) -> InteractionContext:
        """加载并返回新的 interaction_id 上下文；user_id 可为空，不查找或复用已有实例。

        调用方负责 close。创建被取消时，等待加载完成并关闭未交付的实例，再传播取消。
        """
        identity = ContextIdentity(self._character_id, interaction_id, user_id)
        lock = self._user_locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            self._user_locks[user_id] = lock
        created: list[InteractionContext] = []

        async def load() -> InteractionContext:
            async with lock:
                context = await asyncio.to_thread(InteractionContext, identity=identity, database=self._database)
                context._state.lock = lock
                created.append(context)
                return context

        try:
            return await _complete(load())
        except asyncio.CancelledError:
            if created:
                await created[0].close()
            raise
