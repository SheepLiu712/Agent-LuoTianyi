from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, TYPE_CHECKING

from src.system.database.event_models import UnifiedEventType
from src.utils.logger import get_logger
from src.world.types.task_result import WorldTaskResult
from src.world.types.world_task import WorldTask

if TYPE_CHECKING:
    from src.system.system_runtime import SystemRuntime
    from src.world.learn_sing_songs.auto_song_learner import AutoSongLearner
    from src.system.database.event_store import EventStore
    from src.capabilities.singing.singing_manager import SingingManager


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
        self.auto_song_learner: "AutoSongLearner" | None = None
        self._init_error: str = ""

    def initialize(self, system_runtime: "SystemRuntime") -> None:
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

    def run_once(self) -> WorldTaskResult:
        if self.auto_song_learner is None:
            return WorldTaskResult.skipped_result(
                self.task_name,
                self._init_error or "auto song learner is unavailable",
            )

        credential_ok = bool(self.auto_song_learner.check_qq_credential())
        result = self.auto_song_learner.try_learn_pending()
        learned = list(getattr(result, "learned", []) or [])
        abandoned = list(getattr(result, "abandoned", []) or [])
        awaiting = list(getattr(result, "awaiting", []) or [])

        if learned and self.event_store is not None:
            asyncio.run(self._write_learned_event(learned))
        if learned:
            self._reload_singing_library()

        return WorldTaskResult.success(
            self.task_name,
            "song learning pass completed",
            credential_ok=credential_ok,
            learned=learned,
            abandoned=abandoned,
            awaiting=awaiting,
        )

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

