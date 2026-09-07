"""正式对话的近期窗口及总结。"""

import asyncio
from typing import TYPE_CHECKING

from ._lifecycle import _Lifecycle, _complete
from ._storage import _Storage
from .models import (
    CompactionPolicy, CompactionResult, ContextIdentity, ConversationEntry, ConversationSnapshot,
    ConversationSummarizer, ConversationSummary,
)

if TYPE_CHECKING:
    from src.system.database.services.conversation_service import ConversationService


class ConversationContext:
    """由 InteractionContext 创建、负责对话追加和压缩的上下文。"""

    def __init__(
        self, *, snapshot: ConversationSnapshot, identity: ContextIdentity,
        database: "ConversationService", summarizer: ConversationSummarizer | None = None,
        policy: CompactionPolicy = CompactionPolicy(),
    ) -> None:
        """以 snapshot 初始化窗口，绑定 identity、database、总结能力及压缩策略。"""
        self._snapshot = snapshot
        self._summarizer = summarizer
        self._policy = policy
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

    async def compact(self) -> CompactionResult:
        """超过阈值时总结较早对话并保存；返回是否压缩及最新窗口。"""
        return await self._compact()

    def _require_storage(self) -> _Storage:
        self._state.check()
        self._storage.require_user()
        return self._storage

    async def _append(self, entries: tuple[ConversationEntry, ...]) -> None:
        if entries:
            await asyncio.to_thread(self._storage.append, entries)
            self._snapshot, _ = await asyncio.to_thread(self._storage.load_conversation)

    async def _compact(self) -> CompactionResult:
        async with self._state.lock:
            storage = self._require_storage()
            snapshot, count = await _complete(asyncio.to_thread(storage.load_conversation))
            if count <= self._policy.threshold:
                self._snapshot = snapshot
                return CompactionResult(False, snapshot)
            if self._summarizer is None:
                raise RuntimeError("未配置对话总结能力")
            keep = self._policy.keep_recent
            older = snapshot.entries[:-keep] if keep else snapshot.entries
            summary = await self._summarizer.summarize(ConversationSnapshot(snapshot.summary, older))
            if not isinstance(summary, ConversationSummary) or not summary.text.strip():
                raise ValueError("总结能力必须返回非空 ConversationSummary")
            return await _complete(self._save_summary(summary, keep, count))

    async def _save_summary(self, summary: ConversationSummary, keep: int, count: int) -> CompactionResult:
        await asyncio.to_thread(self._storage.compact, summary, keep, count)
        self._snapshot, _ = await asyncio.to_thread(self._storage.load_conversation)
        return CompactionResult(True, self._snapshot)
