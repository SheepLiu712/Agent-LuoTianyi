"""正式对话的近期窗口及总结。"""

import asyncio
from typing import TYPE_CHECKING

from src.infrastructure.persistence.cognitive_maintenance import (
    CognitiveMaintenanceBatch,
    CognitiveMaintenanceBatchDraft,
)

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

    async def read_maintenance_progress(self) -> str | None:
        """读取当前交互对应的持久化认知维护进度。"""
        async with self._state.lock:
            store = self._require_store()
            return await _complete(asyncio.to_thread(store.read_maintenance_progress))

    async def advance_maintenance_progress(self, *, expected_entry_id: str | None, new_entry_id: str) -> bool:
        """在进度仍为 expected_entry_id 时原子推进到 new_entry_id。"""
        async with self._state.lock:
            store = self._require_store()
            return await _complete(
                asyncio.to_thread(
                    store.advance_maintenance_progress,
                    expected_entry_id=expected_entry_id,
                    new_entry_id=new_entry_id,
                )
            )

    async def load_cognitive_maintenance_batch(
        self, *, previous_progress: str | None
    ) -> CognitiveMaintenanceBatch | None:
        """读取该 predecessor 的冻结维护批次，不在此锁内执行模型调用。"""
        async with self._state.lock:
            store = self._require_store()
            return await _complete(
                asyncio.to_thread(store.load_cognitive_maintenance_batch, previous_progress=previous_progress)
            )

    async def create_or_load_cognitive_maintenance_batch(
        self, *, previous_progress: str | None, draft: CognitiveMaintenanceBatchDraft
    ) -> CognitiveMaintenanceBatch:
        """在模型产出后冻结完整输入，重复尝试复用首个持久化结果。"""
        async with self._state.lock:
            store = self._require_store()
            return await _complete(
                asyncio.to_thread(
                    store.create_or_load_cognitive_maintenance_batch,
                    previous_progress=previous_progress,
                    draft=draft,
                )
            )

    async def commit_cognitive_maintenance(
        self,
        *,
        compaction: ConversationCompaction | None,
        expected_progress: str | None,
        new_progress: str,
        maintenance_id: str | None = None,
    ) -> bool:
        """以一个可取消安全的等待边界提交压缩与维护进度。"""
        if compaction is not None and not isinstance(compaction, ConversationCompaction):
            raise TypeError("compaction 应为 ConversationCompaction 或 None")
        async with self._state.lock:
            store = self._require_store()
            succeeded = await _complete(
                asyncio.to_thread(
                    store.commit_cognitive_maintenance,
                    compaction=compaction,
                    expected_progress=expected_progress,
                    new_progress=new_progress,
                    maintenance_id=maintenance_id,
                )
            )
            if succeeded:
                self._snapshot, _ = await asyncio.to_thread(store.load)
            return succeeded

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
