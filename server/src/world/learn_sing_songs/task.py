from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import src.domain.agent as d
from src.system.database.event_models import UnifiedEventType
from src.utils.helpers import get_unified_song_name
from src.utils.logger import get_logger
from src.world.types.task_result import WorldTaskResult
from src.world.types.world_task import WorldTask

if TYPE_CHECKING:
    from src.capabilities.singing.singing_manager import SingingManager
    from src.stage.world_stage import WorldStage
    from src.system.database.services.event_store import EventStore
    from src.system.system_runtime import SystemRuntime
    from src.world.learn_sing_songs.auto_song_learner import AutoSongLearner


class LearnSingSongsTask(WorldTask):
    base_task_name = "learn_sing_songs"

    def __init__(self, config: dict[str, Any] | None = None, character_id: str = "luotianyi", singing_manager: SingingManager | None = None) -> None:
        self.character_id = character_id
        self.singing_manager = singing_manager
        self.character_name: str = getattr(singing_manager, "character_name", "洛天依")
        super().__init__(f"{self.base_task_name}:{character_id}", config)
        self.logger = get_logger(__name__)
        self.system_runtime: SystemRuntime | None = None
        self.event_store: EventStore | None = None
        self.auto_song_learner: AutoSongLearner | None = None
        self._init_error: str = ""

    def initialize(self, system_runtime: SystemRuntime) -> None:
        self.system_runtime = system_runtime
        database_manager = getattr(system_runtime, "database_manager", None)
        self.event_store = getattr(database_manager, "event_store", None)
        self.auto_song_learner = self._build_auto_song_learner()

    def ensure_dependencies(self) -> None:
        """检查学歌任务的基础依赖。"""
        super().ensure_dependencies()
        required = {
            "system_runtime": self.system_runtime,
            "event_store": self.event_store,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise RuntimeError(f"LearnSingSongsTask dependencies are missing: {', '.join(missing)}")

    async def run_once(self) -> WorldTaskResult:
        """执行一次学歌；本任务不生成角色内容，只投递已验证的学会事实。"""
        if self.auto_song_learner is None:
            return WorldTaskResult.skipped_result(
                self.task_name,
                self._init_error or "auto song learner is unavailable",
            )

        credential_ok = bool(self.auto_song_learner.check_qq_credential())
        if not credential_ok:
            return WorldTaskResult.skipped_result(
                self.task_name,
                "QQ Music credential could not be refreshed; song learning was not started",
                credential_ok=False,
            )

        result = self.auto_song_learner.try_learn_pending()
        learned = self._deduplicate_song_names(
            list(getattr(result, "learned", []) or [])
        )
        already_learned = self._deduplicate_song_names(
            list(getattr(result, "already_learned", []) or [])
        )
        already_learned_keys = {
            get_unified_song_name(song_name) for song_name in already_learned
        }
        learned = [
            song_name
            for song_name in learned
            if get_unified_song_name(song_name) not in already_learned_keys
        ]
        abandoned = list(getattr(result, "abandoned", []) or [])
        awaiting = list(getattr(result, "awaiting", []) or [])

        if learned and self.event_store is not None:
            await self._write_learned_event(learned)
        if learned:
            self._reload_singing_library()
            await self._tag_learned_songs(learned)
        submitted = await self._submit_learned(learned)

        return WorldTaskResult.success(
            self.task_name,
            "song learning pass completed",
            credential_ok=credential_ok,
            learned=learned,
            already_learned=already_learned,
            abandoned=abandoned,
            awaiting=awaiting,
            submitted_count=submitted,
        )

    async def _submit_learned(self, learned: list[str]) -> int:
        """把已验证的新学会歌曲逐首投递为世界事实，返回被受理的数量。"""
        if not learned:
            return 0
        stage, character_id = await self._world_stage()
        if stage is None:
            self.logger.warning("WorldStage 不可用，%d 首已学会歌曲本次未投递", len(learned))
            return 0
        job_id = f"{self.character_id}:{datetime.now().strftime('%Y%m%d%H%M%S')}"
        submitted = 0
        for song_name in learned:
            fact = self._build_learned_fact(character_id, job_id, song_name)
            if await stage.fact_sink.submit(fact):
                submitted += 1
            else:
                self.logger.warning("已学会歌曲事实被 WorldStage 拒绝：%s", song_name)
        return submitted

    async def _world_stage(self) -> tuple[WorldStage | None, str]:
        """取得本角色长期 WorldStage；运行时不支持时返回 None。"""
        system_runtime = self.system_runtime
        agent_runtime = getattr(system_runtime, "agent_runtime", None)
        character_id = str(getattr(agent_runtime, "default_character_id", None) or self.character_id)
        get_world_stage = getattr(system_runtime, "get_world_stage", None)
        if not callable(get_world_stage):
            return None, character_id
        return await get_world_stage(character_id), character_id

    def _build_learned_fact(self, character_id: str, job_id: str, song_name: str) -> d.SongLearned:
        """把一次已验证的学会结果包装成强类型世界事实。"""
        now = datetime.now(timezone.utc)
        return d.SongLearned(
            stimulus_id=str(uuid4()),
            schema_version=1,
            occurred_at=now,
            source=d.StimulusSource.WORLD,
            target_character_ids=(character_id,),
            user_id=None,
            ephemeral=False,
            learning_job_id=job_id,
            song_id=song_name,
            completed_at=now,
        )

    @staticmethod
    def _deduplicate_song_names(song_names: list[str]) -> list[str]:
        unique: list[str] = []
        seen: set[str] = set()
        for song_name in song_names:
            display_name = str(song_name or "").strip()
            unified_name = get_unified_song_name(display_name)
            if not display_name or not unified_name or unified_name in seen:
                continue
            seen.add(unified_name)
            unique.append(display_name)
        return unique

    def _build_auto_song_learner(self) -> AutoSongLearner | None:
        try:
            from src.world.learn_sing_songs.auto_song_learner import AutoSongLearner

            manager = self.singing_manager
            if manager is None:
                self._init_error = f"singing manager for {self.character_id} is unavailable"
                return None

            self.singing_manager = manager
            self.character_name = getattr(manager, "character_name", self.character_name)
            wishlist = getattr(manager, "wishlist", None)
            if wishlist is None:
                self._init_error = f"singing wishlist for {self.character_id} is unavailable"
                return None
            resource_path = getattr(manager, "resource_path", None)
            if not resource_path:
                self._init_error = f"singing resource_path for {self.character_id} is unavailable"
                return None
            return AutoSongLearner(self.config, self.character_name, wishlist, resource_path=resource_path)
        except Exception as exc:
            self._init_error = str(exc)
            self.logger.warning(f"LearnSingSongsTask initialization skipped: {exc}")
            return None

    async def _write_learned_event(self, learned: list[str]) -> None:
        if self.event_store is None:
            return
        await self.event_store.add_event(
            {
                "character": self.character_id,
                "title": f"{self.character_name}学会了新歌",
                "description": "、".join(learned),
                "event_type": UnifiedEventType.NEW_SONG.value,
                "start_datetime": datetime.now(),
                "is_recurring": False,
                "source": "world_song_learner",
            }
        )

    def _reload_singing_library(self) -> None:
        if self.system_runtime is None:
            return
        singing = getattr(getattr(self.system_runtime, "capability_manager", None), "singing", None)
        reload_songs = getattr(singing, "reload_songs", None)
        if not callable(reload_songs):
            return
        try:
            reload_songs(self.character_id)
        except Exception as exc:
            self.logger.warning(f"Failed to reload singing library after learning songs: {exc}")

    async def _tag_learned_songs(self, learned: list[str]) -> None:
        if self.system_runtime is None:
            return
        singing = getattr(getattr(self.system_runtime, "capability_manager", None), "singing", None)
        tag_song = getattr(singing, "tag_song_emotions", None)
        if not callable(tag_song):
            return
        for song_name in learned:
            try:
                tags = await tag_song(self.character_id, song_name)
                self.logger.info(f"Song emotion tags generated: {song_name} -> {tags}")
            except Exception as exc:
                self.logger.warning(f"Failed to tag learned song emotions for {song_name}: {exc}")
