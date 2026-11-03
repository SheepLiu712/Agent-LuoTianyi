"""把学歌请求派发到持久学歌任务的愿望清单。"""

from __future__ import annotations

from typing import Protocol

from src.agent.skills.contracts import SkillInvocation


class _SingingManagerAdapter(Protocol):
    """学歌派发与发布材料所需的最小唱歌管理器接口。"""

    def add_wished_song(self, song_id: str) -> bool: ...


class _SingingAdapter(Protocol):
    singing_manager: dict[str, _SingingManagerAdapter]


class SongLearningTasks:
    """包装唱歌能力的愿望清单；派发不等待完整学习流程。"""

    def __init__(self, singing: _SingingAdapter | None) -> None:
        managers = getattr(singing, "singing_manager", None) if singing is not None else None
        if singing is not None and not isinstance(managers, dict):
            raise TypeError("唱歌能力的 singing_manager 必须是角色映射")
        for character_id, manager in (managers or {}).items():
            self._validate_manager(character_id, manager)
        self._singing = singing

    def request(self, invocation: SkillInvocation, *, song_id: str) -> bool:
        """把歌曲加入愿望清单；已在清单中（无论状态）返回 False，重复请求不产生第二个任务。"""
        if not isinstance(song_id, str):
            raise TypeError("song_id 必须是字符串")
        if not song_id.strip():
            raise ValueError("song_id 不能为空")
        manager = self._manager_for(invocation.character_id)
        if manager is None:
            raise RuntimeError("唱歌能力不可用，无法派发学歌任务")
        return bool(manager.add_wished_song(song_id))

    def _manager_for(self, character_id: str) -> _SingingManagerAdapter | None:
        managers = getattr(self._singing, "singing_manager", None) or {}
        manager = managers.get(character_id)
        if manager is None:
            return None
        self._validate_manager(character_id, manager)
        return manager

    @staticmethod
    def _validate_manager(character_id: str, manager: object) -> None:
        missing = tuple(name for name in ("add_wished_song",) if not callable(getattr(manager, name, None)))
        if missing:
            raise TypeError(f"角色 {character_id} 的唱歌管理器缺少可调用方法: {', '.join(missing)}")
