"""把学歌请求派发到持久学歌任务的愿望清单。"""

from __future__ import annotations

from typing import Protocol

from src.agent.skills.contracts import SkillInvocation


class _SingingManagerAdapter(Protocol):
    """学歌派发与发布材料所需的最小唱歌管理器接口。"""

    def add_wished_song(self, song_id: str) -> bool: ...

    def can_i_sing_song(self, song_id: str) -> tuple[str, list[str]]: ...

    def get_full_lyrics(self, song_id: str) -> str: ...

    def get_segment_lyrics(self, song_id: str, segment_description: str) -> str: ...


class _SingingAdapter(Protocol):
    singing_manager: dict[str, _SingingManagerAdapter]


class SongLearningDispatchSkill:
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

    def material(self, invocation: SkillInvocation, *, song_id: str) -> tuple[str, str]:
        """返回可唱唱段描述与歌词（唱段歌词作为后备）；能力不可用时返回空字符串。"""
        if not isinstance(song_id, str):
            raise TypeError("song_id 必须是字符串")
        if not song_id.strip():
            raise ValueError("song_id 不能为空")
        manager = self._manager_for(invocation.character_id)
        if manager is None:
            return "", ""
        correct_name, segments = song_id, []
        try:
            resolved, found = manager.can_i_sing_song(song_id)
            correct_name = str(resolved or song_id)
            segments = list(found or [])
        except Exception:  # noqa: BLE001 - 材料缺失不应阻断学歌事实的结算
            correct_name, segments = song_id, []
        segment_description = str(segments[0]) if segments else ""
        lyrics = ""
        try:
            lyrics = str(manager.get_full_lyrics(correct_name) or "").strip()
        except Exception:  # noqa: BLE001 - 材料缺失不应阻断学歌事实的结算
            lyrics = ""
        if not lyrics and segment_description:
            try:
                lyrics = str(manager.get_segment_lyrics(correct_name, segment_description) or "").strip()
            except Exception:  # noqa: BLE001 - 材料缺失不应阻断学歌事实的结算
                lyrics = ""
        return segment_description, lyrics

    def _manager_for(self, character_id: str) -> _SingingManagerAdapter | None:
        managers = getattr(self._singing, "singing_manager", None) or {}
        manager = managers.get(character_id)
        if manager is None:
            return None
        self._validate_manager(character_id, manager)
        return manager

    @staticmethod
    def _validate_manager(character_id: str, manager: object) -> None:
        missing = tuple(
            name
            for name in ("add_wished_song", "can_i_sing_song", "get_full_lyrics", "get_segment_lyrics")
            if not callable(getattr(manager, name, None))
        )
        if missing:
            raise TypeError(f"角色 {character_id} 的唱歌管理器缺少可调用方法: {', '.join(missing)}")
