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


class LearnSingSongsTask(WorldTask):
    task_name = "learn_sing_songs"

    def __init__(self, config: Dict[str, Any] | None = None, character_id: str = "luotianyi") -> None:
        super().__init__(self.task_name, config)
        self.character_id = character_id
        self.logger = get_logger(__name__)
        self.system_runtime: "SystemRuntime" | None = None
        self.event_store: "EventStore" | None = None
        self.auto_song_learner: "AutoSongLearner" | None = None
        self._init_error: str = ""

    def initialize(self, system_runtime: "SystemRuntime") -> None:
        self.system_runtime = system_runtime
        database_manager = getattr(system_runtime, "database_manager", None)
        self.event_store = getattr(database_manager, "event_store", None)
        self.auto_song_learner = self._build_auto_song_learner(system_runtime)

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

        return WorldTaskResult.success(
            self.task_name,
            "song learning pass completed",
            credential_ok=credential_ok,
            learned=learned,
            abandoned=abandoned,
            awaiting=awaiting,
        )

    def _build_auto_song_learner(self, system_runtime: "SystemRuntime") -> "AutoSongLearner" | None:
        try:
            from src.world.learn_sing_songs.auto_song_learner import AutoSongLearner

            singing = getattr(getattr(system_runtime, "capability_manager", None), "singing", None)
            manager = getattr(singing, "singing_manager", {}).get(self.character_id)
            wishlist = getattr(manager, "wishlist", None)
            if wishlist is None:
                self._init_error = f"singing wishlist for {self.character_id} is unavailable"
                return None
            return AutoSongLearner(self.config, wishlist)
        except Exception as exc:
            self._init_error = str(exc)
            self.logger.warning(f"LearnSingSongsTask initialization skipped: {exc}")
            return None

    async def _write_learned_event(self, learned: list[str]) -> None:
        if self.event_store is None:
            return
        await self.event_store.add_event(
            {
                "title": "洛天依学会了新歌",
                "description": "、".join(learned),
                "event_type": UnifiedEventType.NEW_SONG.value,
                "start_datetime": datetime.now(),
                "is_recurring": False,
                "source": "world_song_learner",
            }
        )
