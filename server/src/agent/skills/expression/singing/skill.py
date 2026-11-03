"""按角色、歌曲与片段渲染演唱音频。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Protocol

from src.agent.skills.contracts import SkillInvocation
from src.agent.skills.expression.song_learning import SongLearningTasks
from src.infrastructure.media.song_asset_validation import playable_segments

from .backend import SingingBackend

if TYPE_CHECKING:
    from src.infrastructure.models.service import LLMService


class _SingingPort(Protocol):
    def sing(self, character_id: str, song_name: str | None = None, segment: str | None = None) -> bytes | None: ...

    def get_song_names(self, character_id: str | None = None) -> tuple[str, ...]: ...


class EmptySongAudioError(Exception):
    """指定片段不可演唱，或没有产生任何音频。"""


class SingingSkill:
    """角色共享的演唱渲染技能；只实现已决定的 Sing 行动，不选择歌曲或片段。"""

    def __init__(
        self,
        config: dict[str, Any],
        llm_service: LLMService | None = None,
        *,
        backend: _SingingPort | None = None,
    ) -> None:
        """校验本层 config，并在 Skill 边界内组装演唱实现。"""
        if not isinstance(config, dict):
            raise TypeError("singing 必须是字典")
        self._singing = backend or SingingBackend(config, llm_service=llm_service)

    def learning_tasks(self) -> SongLearningTasks:
        """提供独立学歌任务资源，Handler 无需接触演唱后端。"""
        return SongLearningTasks(self._singing)

    def song_names(self) -> tuple[str, ...]:
        """返回所有角色曲库中的歌曲名称，供输入实体链接复用。"""
        return self._singing.get_song_names()

    def catalog(self, invocation: SkillInvocation) -> tuple[str, ...]:
        manager = self._singing._get_manager(invocation.character_id)
        return tuple(metadata.song_name for metadata in manager.all_songs.values())

    def canonical_song_id(self, invocation: SkillInvocation, song_id: str) -> str:
        metadata = self._singing._get_manager(invocation.character_id).get_song_metadata(song_id)
        return metadata.song_name if metadata is not None else song_id

    def song_information(self, invocation: SkillInvocation, *, song_id: str, segment_id: str | None = None):
        manager = self._singing._get_manager(invocation.character_id)
        metadata = manager.get_song_metadata(song_id)
        if metadata is None:
            return None
        segments = tuple(segment.description for segment in playable_segments(metadata.segments, metadata.song_path))
        if segment_id is not None and segment_id not in segments:
            return None
        lyrics = (
            manager.get_segment_lyrics(metadata.song_name, segment_id)
            if segment_id is not None
            else manager.get_full_lyrics(metadata.song_name)
        )
        return metadata.song_name, segments, lyrics

    async def select(self, invocation: SkillInvocation, *, attempts: tuple[str, ...], excluded_segments=None):
        return await self._singing.build_sing_plan(
            invocation.character_id, list(attempts), excluded_segments=excluded_segments, confirmed_intent=True
        )

    async def render(self, invocation: SkillInvocation, *, song_id: str, segment_id: str) -> bytes:
        """在 executor 中渲染指定片段；身份为空抛 ValueError，不可用或无音频抛 EmptySongAudioError。"""
        for name, value in (
            ("character_id", invocation.character_id),
            ("song_id", song_id),
            ("segment_id", segment_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} 不能为空")
        data = await asyncio.to_thread(self._singing.sing, invocation.character_id, song_id, segment_id)
        if not data:
            raise EmptySongAudioError(f"{song_id}/{segment_id}")
        return data
