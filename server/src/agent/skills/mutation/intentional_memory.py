"""明确记忆请求的长期存储提交技能。"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class MemoryCommitRevision:
    """底层存储确认的记忆标识及本次是否新写入。"""

    identifier: str
    committed: bool


class _MemoryWriter(Protocol):
    async def commit_user_memory(self, **kwargs) -> tuple[str, bool]: ...


class _Memory(Protocol):
    memory_writer: _MemoryWriter
    vector_store: object
    memory_store: object
    owner_character_id: str


class _Mind(Protocol):
    memory: _Memory


class _Runtime(Protocol):
    mind: _Mind


class IntentionalMemoryCommit:
    """按角色和用户调用既有 MemoryWriter 路径，返回真实提交标识。"""

    def __init__(self, runtime_provider: Callable[[str], _Runtime]) -> None:
        """绑定按角色解析潜意识记忆依赖的提供者。"""
        self._runtime_provider = runtime_provider

    async def commit(
        self, *, character_id: str, user_id: str, content: str,
    ) -> MemoryCommitRevision:
        """提交一条私有用户事实；底层业务去重使重复调用无新副作用。"""
        memory = self._runtime_provider(character_id).mind.memory
        identifier, committed = await memory.memory_writer.commit_user_memory(
            vector_store=memory.vector_store,
            memory_store=memory.memory_store,
            user_id=user_id,
            content=content,
            owner_character_id=memory.owner_character_id,
        )
        return MemoryCommitRevision(identifier=identifier, committed=committed)
