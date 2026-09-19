"""已结算交互的认知维护技能：记忆沉淀与用户画像更新。"""

from __future__ import annotations

from typing import Any, Protocol


class _Memory(Protocol):
    async def write_topic_memories(
        self,
        user_id: str,
        history: str,
        current_dialogue: str = "",
        related_memories: list[str] | None = None,
        commit: bool = True,
    ) -> dict[str, Any]: ...

    async def update_user_profile_by_context(
        self, user_id: str, context: dict[str, Any], commit: bool = True
    ) -> str | None: ...


class ReflectionSkill:
    """通过注入的长期记忆实现沉淀与画像更新，不了解运行时聚合对象。"""

    def __init__(self, config: dict[str, Any], memory: _Memory) -> None:
        if not isinstance(config, dict):
            raise TypeError("reflection 必须是字典")
        self._memory = memory

    async def consolidate_memories(
        self,
        *,
        character_id: str,
        user_id: str,
        current_dialogue: str,
        conversation_history: str = "",
        related_memories: list[str] | None = None,
    ) -> dict[str, Any]:
        _ = character_id
        return await self._memory.write_topic_memories(
            user_id=user_id,
            history=conversation_history,
            current_dialogue=current_dialogue,
            related_memories=related_memories or [],
            commit=True,
        )

    async def update_profile(
        self, *, character_id: str, user_id: str, summary: str, recent_conversation: list[str]
    ) -> str | None:
        _ = character_id
        return await self._memory.update_user_profile_by_context(
            user_id=user_id,
            context={"summary": summary, "recent_conversation": list(recent_conversation)},
        )
