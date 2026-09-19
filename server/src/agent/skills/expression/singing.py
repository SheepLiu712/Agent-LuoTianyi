"""按角色、歌曲与片段渲染演唱音频。"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol


class _SingingPort(Protocol):
    def sing(self, character_id: str, song_name: str | None = None, segment: str | None = None) -> bytes | None: ...


class EmptySongAudioError(Exception):
    """指定片段不可演唱，或没有产生任何音频。"""


class SingingSkill:
    """角色共享的演唱渲染技能；只实现已决定的 Sing 行动，不选择歌曲或片段。"""

    def __init__(self, config: dict[str, Any], singing: _SingingPort) -> None:
        """校验本层 config 并绑定演唱能力。"""
        if not isinstance(config, dict):
            raise TypeError("singing 必须是字典")
        self._singing = singing

    async def render(self, *, character_id: str, song_id: str, segment_id: str) -> bytes:
        """在 executor 中渲染指定片段；身份为空抛 ValueError，不可用或无音频抛 EmptySongAudioError。"""
        for name, value in (("character_id", character_id), ("song_id", song_id), ("segment_id", segment_id)):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} 不能为空")
        data = await asyncio.to_thread(self._singing.sing, character_id, song_id, segment_id)
        if not data:
            raise EmptySongAudioError(f"{song_id}/{segment_id}")
        return data
