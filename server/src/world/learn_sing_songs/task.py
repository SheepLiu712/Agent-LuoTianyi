from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, TYPE_CHECKING

from src.system.database.event_models import UnifiedEventType
from src.utils.helpers import get_unified_song_name
from src.utils.logger import get_logger
from src.world.types.task_result import WorldTaskResult
from src.world.types.world_task import WorldTask

if TYPE_CHECKING:
    from src.system.system_runtime import SystemRuntime
    from src.world.learn_sing_songs.auto_song_learner import AutoSongLearner
    from src.system.database.event_store import EventStore
    from src.capabilities.singing.singing_manager import SingingManager
    from src.agent_runtime.character_runtime import CharacterRuntime


class LearnSingSongsTask(WorldTask):
    base_task_name = "learn_sing_songs"

    def __init__(self, config: Dict[str, Any] | None = None, character_id: str = "luotianyi", singing_manager: "SingingManager" | None = None) -> None:
        self.character_id = character_id
        self.singing_manager = singing_manager
        self.character_name: str = getattr(singing_manager, "character_name", "洛天依")
        super().__init__(f"{self.base_task_name}:{character_id}", config)
        self.logger = get_logger(__name__)
        self.system_runtime: "SystemRuntime" | None = None
        self.event_store: "EventStore" | None = None
        self.character_runtime: "CharacterRuntime" | None = None
        self.auto_song_learner: "AutoSongLearner" | None = None
        self._init_error: str = ""

    def initialize(self, system_runtime: "SystemRuntime") -> None:
        self.system_runtime = system_runtime
        database_manager = getattr(system_runtime, "database_manager", None)
        self.event_store = getattr(database_manager, "event_store", None)
        agent_runtime = getattr(system_runtime, "agent_runtime", None)
        self.character_runtime = agent_runtime.get_character_runtime(self.character_id) if agent_runtime is not None else None
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

    def run_once(self) -> WorldTaskResult:
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
            asyncio.run(self._write_learned_event(learned))
        if learned:
            self._reload_singing_library()
            self._tag_learned_songs(learned)
            published_dynamic_ids = self._publish_learned_dynamics(learned)
        else:
            published_dynamic_ids = []

        return WorldTaskResult.success(
            self.task_name,
            "song learning pass completed",
            credential_ok=credential_ok,
            learned=learned,
            already_learned=already_learned,
            abandoned=abandoned,
            awaiting=awaiting,
            dynamic_ids=published_dynamic_ids,
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

    def _build_auto_song_learner(self) -> "AutoSongLearner" | None:
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

    def _tag_learned_songs(self, learned: list[str]) -> None:
        if self.system_runtime is None:
            return
        singing = getattr(getattr(self.system_runtime, "capability_manager", None), "singing", None)
        tag_song = getattr(singing, "tag_song_emotions", None)
        if not callable(tag_song):
            return
        for song_name in learned:
            try:
                tags = asyncio.run(tag_song(self.character_id, song_name))
                self.logger.info(f"Song emotion tags generated: {song_name} -> {tags}")
            except Exception as exc:
                self.logger.warning(f"Failed to tag learned song emotions for {song_name}: {exc}")

    def _publish_learned_dynamics(self, learned: list[str]) -> list[str]:
        if self.character_runtime is None:
            return []
        published: list[str] = []
        for song_name in learned:
            material = self._collect_learned_song_material(song_name)
            try:
                result = asyncio.run(
                    self.character_runtime.publish_learned_song_dynamic(
                        song_name=song_name,
                        segment_description=material.get("segment_description", ""),
                        lyrics=material.get("lyrics", ""),
                    )
                )
                dynamic_id = result.get("dynamic_id")
                if dynamic_id and result.get("created", True):
                    published.append(str(dynamic_id))
            except Exception as exc:
                self.logger.warning(f"Failed to publish learned-song dynamic for {song_name}: {exc}")
        return published

    def _collect_learned_song_material(self, song_name: str) -> dict[str, str]:
        manager = self.singing_manager
        if manager is None:
            return {"song_name": song_name, "segment_description": "", "lyrics": ""}

        correct_song_name = song_name
        segment_description = ""
        try:
            resolved_name, segments = manager.can_i_sing_song(song_name)
            if resolved_name:
                correct_song_name = resolved_name
            if segments:
                segment_description = str(segments[0])
        except Exception as exc:
            self.logger.warning(f"Failed to resolve learned song segments for {song_name}: {exc}")

        lyrics = ""
        get_full_lyrics = getattr(manager, "get_full_lyrics", None)
        if callable(get_full_lyrics):
            try:
                lyrics = str(get_full_lyrics(correct_song_name or song_name) or "").strip()
            except Exception as exc:
                self.logger.warning(f"Failed to read full lyrics for {song_name}: {exc}")

        if not lyrics and segment_description:
            get_segment_lyrics = getattr(manager, "get_segment_lyrics", None)
            if callable(get_segment_lyrics):
                try:
                    lyrics = str(get_segment_lyrics(correct_song_name or song_name, segment_description) or "").strip()
                except Exception as exc:
                    self.logger.warning(f"Failed to read segment lyrics for {song_name}: {exc}")

        return {
            "song_name": correct_song_name or song_name,
            "segment_description": segment_description,
            "lyrics": lyrics,
        }

