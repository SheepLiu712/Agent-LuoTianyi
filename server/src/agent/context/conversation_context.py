"""正式对话的近期窗口及总结。"""

import asyncio
from typing import TYPE_CHECKING

from ._lifecycle import _Lifecycle, _complete
from ._storage import _Storage
from .models import (
    ConversationCompaction, ContextIdentity, ConversationEntry, ConversationSnapshot,
    ConversationSummary,
)

if TYPE_CHECKING:
    from src.system.database.services.conversation_service import ConversationService


class ConversationContext:
    """由 InteractionContext 创建、负责对话追加和压缩的上下文。"""

    def __init__(
        self, *, snapshot: ConversationSnapshot, identity: ContextIdentity,
        database: "ConversationService",
    ) -> None:
        """以 snapshot 初始化窗口，绑定 identity、database。"""
        self._snapshot = snapshot
        self._state = _Lifecycle()
        self._storage = _Storage(database, identity)

    def read(self) -> ConversationSnapshot:
        """返回旧总结和按时间排列的近期对话。"""
        self._state.check()
        return self._snapshot

    async def append(self, entries: tuple[ConversationEntry, ...]) -> None:
        """持久化 entries 后刷新窗口；与同一用户、角色的压缩操作顺序执行。"""
        if not isinstance(entries, tuple) or any(not isinstance(e, ConversationEntry) for e in entries):
            raise TypeError("entries 应为 ConversationEntry 元组")
        async with self._state.lock:
            self._require_storage()
            await _complete(self._append(entries))

    async def compact(self, compaction: ConversationCompaction) -> None:
        """验证并保存外部压缩结果，保留未覆盖的记录及完整历史。

        compaction 必须包含原总结、连续前缀记录 ID 和新总结；
        原总结或记录不匹配时抛 ValueError，保存失败时抛 RuntimeError。
        """
        if not isinstance(compaction, ConversationCompaction):
            raise TypeError("compaction 应为 ConversationCompaction")
        async with self._state.lock:
            storage = self._require_storage()
            snapshot, count = await _complete(asyncio.to_thread(storage.load_conversation))
            covered = compaction.covered_entry_ids
            prefix = tuple(entry.entry_id for entry in snapshot.entries[:len(covered)])
            if snapshot.summary != compaction.previous_summary or prefix != covered:
                raise ValueError("压缩依据与当前对话上下文不匹配")
            keep = count - len(covered)
            if keep < 0:
                raise ValueError("被覆盖的对话数超过当前窗口条数")
            await _complete(self._save_summary(compaction.summary, keep, count))

    def _require_storage(self) -> _Storage:
        self._state.check()
        self._storage.require_user()
        return self._storage

    async def _append(self, entries: tuple[ConversationEntry, ...]) -> None:
        if entries:
            await asyncio.to_thread(self._storage.append, entries)
            self._snapshot, _ = await asyncio.to_thread(self._storage.load_conversation)

    async def _save_summary(self, summary: ConversationSummary, keep: int, count: int) -> None:
        await asyncio.to_thread(self._storage.compact, summary, keep, count)
        self._snapshot, _ = await asyncio.to_thread(self._storage.load_conversation)
