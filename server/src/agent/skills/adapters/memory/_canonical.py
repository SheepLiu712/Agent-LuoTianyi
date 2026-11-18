"""旧记忆入口共享的正本只读一致性检查，不改变提交语义。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.domain.memory_record import MemoryRecord
from src.utils.asyncio_helpers import run_sync_owned

if TYPE_CHECKING:
    from src.infrastructure.persistence.database.services.memory_store import MemoryStore


async def find_matching_record(memory_store: MemoryStore, expected: MemoryRecord) -> MemoryRecord | None:
    """读取同一身份的正本；内容不一致时失败，不创建或提交记录。"""
    existing = await run_sync_owned(memory_store.get_agent_memory_record, expected.id)
    if existing is not None and (
        existing.owner_character_id != expected.owner_character_id
        or existing.subject_user_id != expected.subject_user_id
        or existing.memory_type != expected.memory_type
        or existing.visibility != expected.visibility
        or existing.source != expected.source
        or existing.content != expected.content
    ):
        raise ValueError("memory identity conflicts with persisted content")
    return existing
