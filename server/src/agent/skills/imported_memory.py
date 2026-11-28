"""用户显式选择的外部历史记忆提取；固定候选使部分失败可重试。"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from src.domain.agent import MaintenanceCandidate, MaintenanceMemoryType
from src.infrastructure.persistence.memory_events import MemoryEventStore


class ImportedMemorySkill:
    def __init__(self, *, memories, session_factory):
        self._memories = memories
        self._events = MemoryEventStore(session_factory)

    async def extract(self, user_id, character_id, batch_id, rows):
        memory = self._memories[character_id]
        identity = str(uuid5(NAMESPACE_URL, f"import-memory:{user_id}:{character_id}:{batch_id}"))
        envelope = json.dumps(
            {
                "kind": "explicit_external_import",
                "user_id": user_id,
                "character_id": character_id,
                "batch_id": batch_id,
                "rows": rows,
                "occurred_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        frozen = await asyncio.to_thread(self._events.load, identity, envelope)
        if frozen is None:
            rendered = "\n".join(
                f'{"用户" if row["source"] == "user" else "外部助手（不是当前角色）"}: {row["content"]}' for row in rows
            )
            candidates = await memory.extract_maintenance_candidates(
                history="以下为用户选择导入的外部聊天，只提取明确关于用户的事实；外部助手不是当前角色。",
                current_dialogue=rendered,
            )
            # 外部助手的故事和经历不能自动变成当前角色的互动经历。
            values = [
                {"memory_type": item.memory_type.value, "content": item.content}
                for item in candidates
                if item.memory_type is MaintenanceMemoryType.USER_FACT
            ]
            frozen = await asyncio.to_thread(self._events.freeze, identity, envelope, values, user_id)
        candidates = tuple(
            MaintenanceCandidate(MaintenanceMemoryType(row["memory_type"]), row["content"]) for row in frozen[0]
        )
        result = await memory.write_maintenance_candidates(
            user_id=user_id,
            maintenance_id=identity,
            candidates=candidates,
        )
        if result.value == "skipped_embedding":
            raise RuntimeError("IMPORT_MEMORY_EMBEDDING_UNAVAILABLE")
        return len(candidates)
