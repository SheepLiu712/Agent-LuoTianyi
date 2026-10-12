"""正式对话的近期窗口及总结。"""

import asyncio
from typing import TYPE_CHECKING

from ._lifecycle import _complete, _Lifecycle
from .conversation_store import ConversationStore, DatabaseConversationStore
from .models import (
    ContextIdentity,
    ConversationCompaction,
    ConversationEntry,
    ConversationSnapshot,
)

if TYPE_CHECKING:
    from src.infrastructure.persistence.database.services.conversation_service import ConversationService


class ConversationContext:
    """由 InteractionContext 创建、负责对话追加和压缩的上下文。"""

    def __init__(
        self,
        *,
        identity: ContextIdentity,
        database: "ConversationService | None" = None,
        store: ConversationStore | None = None,
        snapshot: ConversationSnapshot | None = None,
    ) -> None:
        """绑定 identity 和 Store；默认使用数据库 Store。"""
        self._state = _Lifecycle()
        if store is None:
            if database is None:
                raise TypeError("database 或 store 必须提供")
            store = DatabaseConversationStore(database, identity)
        self._store = store
        self._snapshot = snapshot if snapshot is not None else self._store.load()[0]

    def read(self) -> ConversationSnapshot:
        """返回旧总结和按时间排列的近期对话。"""
        self._state.check()
        return self._snapshot

    async def append(self, entries: tuple[ConversationEntry, ...]) -> None:
        """追加 entries 后刷新窗口；与同一用户、角色的压缩操作顺序执行。"""
        if not isinstance(entries, tuple) or any(not isinstance(e, ConversationEntry) for e in entries):
            raise TypeError("entries 应为 ConversationEntry 元组")
        async with self._state.lock:
            self._require_store()
            await _complete(self._append(entries))

    async def compact(self, compaction: ConversationCompaction) -> None:
        """验证并保存外部压缩结果，保留未覆盖的记录及完整历史。

        compaction 必须包含原总结、连续前缀记录 ID 和新总结；
        原总结或记录不匹配时抛 ValueError，保存失败时抛 RuntimeError。
        """
        if not isinstance(compaction, ConversationCompaction):
            raise TypeError("compaction 应为 ConversationCompaction")
        async with self._state.lock:
            self._require_store()
            await _complete(self._compact(compaction))

    def _require_store(self) -> ConversationStore:
        self._state.check()
        require_user = getattr(self._store, "require_user", None)
        if require_user is not None:
            require_user()
        return self._store

    def _close_store(self) -> None:
        self._store.close()

    async def _append(self, entries: tuple[ConversationEntry, ...]) -> None:
        if entries:
            await asyncio.to_thread(self._store.append, entries)
            self._snapshot, _ = await asyncio.to_thread(self._store.load)

    async def _compact(self, compaction: ConversationCompaction) -> None:
        await asyncio.to_thread(self._store.compact, compaction)
        self._snapshot, _ = await asyncio.to_thread(self._store.load)
