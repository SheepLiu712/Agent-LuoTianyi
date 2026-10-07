"""按触发刺激管理交互内的召回结果。"""

from copy import deepcopy

from ._lifecycle import _Lifecycle
from .models import RecallEntry


class RecalledMemoryContext:
    """仅保存在当前交互中的召回记录集合。"""

    def __init__(self) -> None:
        """创建空的召回缓存。"""
        self._state = _Lifecycle()
        self._entries: dict[str, RecallEntry] = {}

    def read(self) -> tuple[RecallEntry, ...]:
        """返回按添加顺序排列的记录副本，修改副本不会改变缓存。"""
        self._state.check()
        return deepcopy(tuple(self._entries.values()))

    def append(self, entries: tuple[RecallEntry, ...]) -> None:
        """添加一组召回记录；记录 ID 重复时整组拒绝并抛 ValueError。"""
        self._state.check()
        if not isinstance(entries, tuple) or any(not isinstance(e, RecallEntry) for e in entries):
            raise TypeError("entries 应为 RecallEntry 元组")
        ids = {entry.entry_id for entry in entries}
        if len(ids) != len(entries) or ids.intersection(self._entries):
            raise ValueError("召回记录 ID 重复")
        self._entries.update((entry.entry_id, deepcopy(entry)) for entry in entries)

    def remove(self, entry_ids: frozenset[str]) -> None:
        """删除指定记录 ID；不存在的 ID 不产生影响。"""
        self._state.check()
        for entry_id in entry_ids:
            self._entries.pop(entry_id, None)

    def remove_by_stimulus_id(self, stimulus_id: str) -> None:
        """删除由指定刺激触发的全部召回记录。"""
        self._state.check()
        self.remove(frozenset(e.entry_id for e in self._entries.values() if e.stimulus_id == stimulus_id))

    def clear(self) -> None:
        """移除当前交互中的全部召回记录。"""
        self._state.check()
        self._entries.clear()
