"""正式对话窗口的存储边界。"""

from typing import TYPE_CHECKING, Protocol

from ._storage import _Storage
from .models import ContextIdentity, ConversationCompaction, ConversationEntry, ConversationSnapshot

if TYPE_CHECKING:
    from src.infrastructure.persistence.database.services.conversation_service import ConversationService


class ConversationStore(Protocol):
    """保存并读取一个对话上下文窗口的窄端口。"""

    def load(self) -> tuple[ConversationSnapshot, int]:
        """返回当前总结、未压缩条目及其窗口条目数。"""

    def append(self, entries: tuple[ConversationEntry, ...]) -> None:
        """追加正式对话条目。"""

    def compact(self, compaction: ConversationCompaction) -> None:
        """仅当 compaction 覆盖当前连续前缀时替换总结。"""

    def close(self) -> None:
        """释放 Store 持有的交互内容；持久化 Store 可以为空操作。"""


class DatabaseConversationStore:
    """忠实包装现有 _Storage 的正式聊天对话持久化行为。"""

    def __init__(self, database: "ConversationService", identity: ContextIdentity) -> None:
        self._storage = _Storage(database, identity)

    def load(self) -> tuple[ConversationSnapshot, int]:
        return self._storage.load_conversation()

    def append(self, entries: tuple[ConversationEntry, ...]) -> None:
        self._storage.append(entries)

    def compact(self, compaction: ConversationCompaction) -> None:
        snapshot, count = self.load()
        keep = _validate_compaction(snapshot, count, compaction)
        self._storage.compact(compaction.summary, keep, count)

    def close(self) -> None:
        """数据库事实不随交互 Context 关闭而删除。"""

    def require_user(self) -> str:
        """保留正式数据库对话对用户身份的既有要求。"""
        return self._storage.require_user()


class EphemeralCallConversationStore:
    """只保存一次呼叫工作窗口的内存 Store，不持有数据库引用。"""

    def __init__(self, seed: ConversationSnapshot | None = None) -> None:
        seed = seed or ConversationSnapshot()
        entries = tuple(sorted(seed.entries, key=lambda entry: entry.timestamp))
        self._snapshot = ConversationSnapshot(seed.summary, entries)

    def load(self) -> tuple[ConversationSnapshot, int]:
        return self._snapshot, len(self._snapshot.entries)

    def append(self, entries: tuple[ConversationEntry, ...]) -> None:
        if not entries:
            return
        merged = (*self._snapshot.entries, *entries)
        ordered_entries = tuple(sorted(merged, key=lambda entry: entry.timestamp))
        self._snapshot = ConversationSnapshot(self._snapshot.summary, ordered_entries)

    def compact(self, compaction: ConversationCompaction) -> None:
        snapshot, count = self.load()
        keep = _validate_compaction(snapshot, count, compaction)
        self._snapshot = ConversationSnapshot(compaction.summary, snapshot.entries[-keep:] if keep else ())

    def close(self) -> None:
        """清除可能包含逐轮转录或工作摘要的呼叫内存。"""
        self._snapshot = ConversationSnapshot()


def _validate_compaction(snapshot: ConversationSnapshot, count: int, compaction: ConversationCompaction) -> int:
    covered = compaction.covered_entry_ids
    prefix = tuple(entry.entry_id for entry in snapshot.entries[: len(covered)])
    if snapshot.summary != compaction.previous_summary or prefix != covered:
        raise ValueError("压缩依据与当前对话上下文不匹配")
    keep = count - len(covered)
    if keep < 0:
        raise ValueError("被覆盖的对话数超过当前窗口条数")
    return keep
