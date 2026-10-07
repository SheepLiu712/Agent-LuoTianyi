"""把动态正文与评论写入用户长期记忆。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.agent.skills.adapters.memory import AgentMemory
from src.agent.skills.contracts import SkillInvocation


class DynamicTopicMemorySkill:
    """动态互动的记忆写入技能。

    记忆写入与回复可用性完全解耦：调用方在回复之前独立提交，失败只记录；
    写入结果（是否真的产生了记忆）只在这里判定，世界侧不再解读记忆返回值。
    """

    def __init__(self, memories: Mapping[str, AgentMemory]) -> None:
        self._memories = dict(memories)

    async def write(
        self,
        invocation: SkillInvocation,
        *,
        current_dialogue: str,
        conversation_history: str,
    ) -> bool:
        """写一轮话题记忆；真正写入至少一条记忆时返回 True。"""
        user_id = invocation.require_user_id()
        for name, value in (("user_id", user_id), ("current_dialogue", current_dialogue)):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} 不能为空")
        try:
            memory = self._memories[invocation.character_id]
        except KeyError as error:
            raise RuntimeError("角色记忆不可用，无法写入动态记忆") from error
        result: dict[str, Any] = await memory.write_topic_memories(
            user_id=user_id,
            history=conversation_history or "",
            current_dialogue=current_dialogue,
            related_memories=[],
            commit=True,
        )
        return any(str(item.get("status") or "") == "written" for item in (result or {}).get("items") or [])
