"""把「学会一首歌」写入角色自身经验记忆。"""

from __future__ import annotations

from src.subconscious.memory import SubconsciousMemory


class LearnedSongExperienceSkill:
    """角色共享的学会经验写入技能。

    经验写入角色自身的事件记忆，记忆作用域使用角色 ID，避免污染任何用户记忆；
    同日同内容由既有事件记忆去重保证幂等，因此同一学习任务重投不会产生第二条经验。
    """

    def __init__(self, memory: SubconsciousMemory | None) -> None:
        self._memory = memory

    async def commit(self, *, character_id: str, song_id: str, learning_job_id: str) -> bool:
        """写入一条学会经验；已有同日同内容记录时返回 False，不重复写入。"""
        for name, value in (
            ("character_id", character_id),
            ("song_id", song_id),
            ("learning_job_id", learning_job_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} 不能为空")
        if self._memory is None:
            raise RuntimeError("角色记忆不可用，无法写入学会经验")
        content = f"学会了新歌《{song_id}》（学习任务 {learning_job_id}）"
        return await self._memory.write_event_memory(user_id=character_id, content=content)
