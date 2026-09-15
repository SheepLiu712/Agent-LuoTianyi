"""把学歌请求派发到持久学歌任务的愿望清单。"""

from __future__ import annotations

from typing import Any


class SongLearningDispatchSkill:
    """包装唱歌能力的愿望清单；派发不等待完整学习流程。"""

    def __init__(self, singing_manager: Any | None) -> None:
        self._singing = singing_manager

    def request(self, *, song_id: str) -> bool:
        """把歌曲加入愿望清单；已在清单中（无论状态）返回 False，重复请求不产生第二个任务。"""
        if not isinstance(song_id, str):
            raise TypeError("song_id 必须是字符串")
        if not song_id.strip():
            raise ValueError("song_id 不能为空")
        if self._singing is None:
            raise RuntimeError("唱歌能力不可用，无法派发学歌任务")
        add_wished_song = getattr(self._singing, "add_wished_song", None)
        if not callable(add_wished_song):
            raise RuntimeError("唱歌能力不支持愿望清单")
        return bool(add_wished_song(song_id))

    def material(self, *, song_id: str) -> tuple[str, str]:
        """返回可唱唱段描述与歌词（唱段歌词作为后备）；能力不可用时返回空字符串。"""
        if not isinstance(song_id, str):
            raise TypeError("song_id 必须是字符串")
        if not song_id.strip():
            raise ValueError("song_id 不能为空")
        if self._singing is None:
            return "", ""
        correct_name, segments = song_id, []
        can_i_sing = getattr(self._singing, "can_i_sing_song", None)
        if callable(can_i_sing):
            try:
                resolved, found = can_i_sing(song_id)
                correct_name = str(resolved or song_id)
                segments = list(found or [])
            except Exception:  # noqa: BLE001 - 材料缺失不应阻断学歌事实的结算
                correct_name, segments = song_id, []
        segment_description = str(segments[0]) if segments else ""
        lyrics = ""
        get_full_lyrics = getattr(self._singing, "get_full_lyrics", None)
        if callable(get_full_lyrics):
            try:
                lyrics = str(get_full_lyrics(correct_name) or "").strip()
            except Exception:  # noqa: BLE001
                lyrics = ""
        if not lyrics and segment_description:
            get_segment_lyrics = getattr(self._singing, "get_segment_lyrics", None)
            if callable(get_segment_lyrics):
                try:
                    lyrics = str(get_segment_lyrics(correct_name, segment_description) or "").strip()
                except Exception:  # noqa: BLE001
                    lyrics = ""
        return segment_description, lyrics
