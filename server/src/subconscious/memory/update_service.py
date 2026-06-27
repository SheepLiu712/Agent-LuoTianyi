from __future__ import annotations

from typing import Any, List, TYPE_CHECKING

from sqlalchemy.orm import Session

from src.system.database.redis_buffer import RedisBuffer

if TYPE_CHECKING:
    from src.subconscious.memory.facade import SubconsciousMemory


class MemoryUpdateService:
    """Single entry point for memory mutations in the subconscious layer."""

    def __init__(self, config: dict[str, Any], memory: "SubconsciousMemory"):
        self.config = config
        self.memory = memory

    async def post_process_interaction(
        self,
        db: Session,
        redis: RedisBuffer,
        user_id: str,
        history: str,
        current_dialogue: str = "",
        related_memories: List[str] | None = None,
        commit: bool = True,
    ) -> None:
        await self.memory.post_process_interaction(
            db=db,
            redis=redis,
            user_id=user_id,
            history=history,
            current_dialogue=current_dialogue,
            related_memories=related_memories or [],
            commit=commit,
        )

    async def write_user_memory(
        self,
        db: Session,
        redis: RedisBuffer,
        user_id: str,
        content: str,
        commit: bool = True,
    ) -> bool:
        return await self.memory.write_user_memory(
            db=db,
            redis=redis,
            user_id=user_id,
            content=content,
            commit=commit,
        )

    async def write_event_memory(
        self,
        db: Session,
        redis: RedisBuffer,
        user_id: str,
        content: str,
        commit: bool = True,
    ) -> bool:
        return await self.memory.write_event_memory(
            db=db,
            redis=redis,
            user_id=user_id,
            content=content,
            commit=commit,
        )

    async def update_user_profile_by_context(
        self,
        db: Session,
        redis: RedisBuffer,
        user_id: str,
        context: dict[str, Any],
        commit: bool = True,
    ) -> str | None:
        return await self.memory.update_user_profile_by_context(
            db=db,
            redis=redis,
            user_id=user_id,
            context=context,
            commit=commit,
        )
