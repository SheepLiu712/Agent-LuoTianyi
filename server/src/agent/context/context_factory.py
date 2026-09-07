"""按交互取得和释放角色上下文。"""

import asyncio
from typing import TYPE_CHECKING

from ._lifecycle import _complete
from .interaction_context import InteractionContext
from .models import CompactionPolicy, ContextIdentity, ConversationSummarizer

if TYPE_CHECKING:
    from src.system.database.services.conversation_service import ConversationService


class ContextFactory:
    """为一个角色持有交互上下文；同一实例在一个事件循环内使用。"""

    def __init__(
        self, *, character_id: str, database: "ConversationService",
        summarizer: ConversationSummarizer | None = None,
        policy: CompactionPolicy = CompactionPolicy(),
    ) -> None:
        """绑定 character_id、数据库服务 database，以及总结能力和压缩策略。"""
        if not isinstance(character_id, str) or not character_id.strip():
            raise ValueError("角色标识不能为空")
        self._character_id = character_id
        self._database = database
        self._summarizer = summarizer
        self._policy = policy
        self._contexts: dict[str, InteractionContext] = {}
        self._lock = asyncio.Lock()
        self._user_locks: dict[str | None, asyncio.Lock] = {}

    async def get(self, interaction_id: str, *, user_id: str | None) -> InteractionContext:
        """返回 interaction_id 的上下文，不存在则加载创建；已有交互不能更换 user_id。"""
        identity = ContextIdentity(self._character_id, interaction_id, user_id)
        return await _complete(self._get(identity))

    def find(self, interaction_id: str) -> InteractionContext | None:
        """查找已创建且未关闭的上下文；找不到时返回 None。"""
        context = self._contexts.get(interaction_id)
        return context if context is not None and not context._state.closed else None

    async def release(self, interaction_id: str) -> None:
        """关闭并移除 interaction_id 的上下文；交互不存在时无影响。"""
        await _complete(self._release(interaction_id))

    async def _get(self, identity: ContextIdentity) -> InteractionContext:
        async with self._lock:
            context = self._contexts.get(identity.interaction_id)
            if context is not None:
                if context.identity != identity:
                    raise ValueError("同一交互不能更换用户")
                if not context._state.closed:
                    return context
            context = await asyncio.to_thread(
                InteractionContext, identity=identity, database=self._database,
                summarizer=self._summarizer, policy=self._policy,
            )
            context._state.lock = self._user_locks.setdefault(identity.user_id, asyncio.Lock())
            self._contexts[identity.interaction_id] = context
            return context

    async def _release(self, interaction_id: str) -> None:
        async with self._lock:
            context = self._contexts.get(interaction_id)
            if context is None:
                return
            await context.close()
            del self._contexts[interaction_id]
            user_id = context.identity.user_id
            if not any(c.identity.user_id == user_id for c in self._contexts.values()):
                self._user_locks.pop(user_id, None)
