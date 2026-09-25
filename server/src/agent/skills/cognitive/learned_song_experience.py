"""把「学会一首歌」写入角色自身经验记忆。"""

from __future__ import annotations

from collections.abc import Mapping

from src.agent.skills.adapters.memory import AgentMemory
from src.agent.skills.contracts import SkillInvocation


class LearnedSongExperienceSkill:
    """角色共享的学会经验写入技能。

    经验写入角色自身的事件记忆，记忆作用域使用角色 ID，避免污染任何用户记忆；
    同日同内容由既有事件记忆去重保证幂等，因此同一学习任务重投不会产生第二条经验。
    """

    def __init__(self, memories: Mapping[str, AgentMemory]) -> None:
        self._memories = dict(memories)

    async def commit(self, invocation: SkillInvocation, *, song_id: str, learning_job_id: str) -> bool:
        """写入一条学会经验；已有同日同内容记录时返回 False，不重复写入。"""
        for name, value in (
            ("character_id", invocation.character_id),
            ("song_id", song_id),
            ("learning_job_id", learning_job_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} 不能为空")
        try:
            memory = self._memories[invocation.character_id]
        except KeyError as error:
            raise RuntimeError("角色记忆不可用，无法写入学会经验") from error
        content = f"学会了新歌《{song_id}》（学习任务 {learning_job_id}）"
        return await memory.write_event_memory(user_id=invocation.character_id, content=content)
