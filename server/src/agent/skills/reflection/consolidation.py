"""已结算交互的认知维护技能：记忆沉淀与用户画像更新。"""

from __future__ import annotations

from typing import Any, Callable, Protocol


class _Mind(Protocol):
    async def write_topic_memories(
        self, user_id: str, current_dialogue: str, related_memories=None, conversation_history=None
    ): ...
    async def update_user_profile_by_context(self, user_id: str, context: dict): ...


class _Runtime(Protocol):
    mind: _Mind


class ReflectionSkill:
    """包装角色潜意识的记忆写入与画像更新，只维护长期认知数据，不产生用户可见输出。"""

    def __init__(self, config: dict[str, Any], runtime_provider: Callable[[str], _Runtime]) -> None:
        """校验本层 config 并绑定按角色解析潜意识的提供者。"""
        if not isinstance(config, dict):
            raise TypeError("reflection 必须是字典")
        self._runtime_provider = runtime_provider

    async def consolidate_memories(
        self,
        *,
        character_id: str,
        user_id: str,
        current_dialogue: str,
        conversation_history: str = "",
        related_memories: list[str] | None = None,
    ) -> dict[str, Any]:
        """依据本次已结算对话提取并写入长期记忆，返回底层提交结果。"""
        runtime = self._runtime_provider(character_id)
        return await runtime.mind.write_topic_memories(
            user_id=user_id,
            current_dialogue=current_dialogue,
            related_memories=related_memories,
            conversation_history=conversation_history,
        )

    async def update_profile(
        self, *, character_id: str, user_id: str, summary: str, recent_conversation: list[str]
    ) -> str | None:
        """按当前对话总结与近期对话更新用户画像；无更新时返回 None。"""
        runtime = self._runtime_provider(character_id)
        return await runtime.mind.update_user_profile_by_context(
            user_id=user_id, context={"summary": summary, "recent_conversation": list(recent_conversation)}
        )
