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
        self.dynamic_capability: Any | None = None
        self.dynamic_capability: Any | None = None
        self.auto_song_learner: "AutoSongLearner" | None = None
        self._init_error: str = ""

    def initialize(self, system_runtime: "SystemRuntime") -> None:
        self.system_runtime = system_runtime
        database_manager = getattr(system_runtime, "database_manager", None)
        self.event_store = getattr(database_manager, "event_store", None)
        self.dynamic_capability = getattr(getattr(system_runtime, "capability_manager", None), "dynamics", None)
        self.dynamic_capability = getattr(getattr(system_runtime, "capability_manager", None), "dynamics", None)
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
            published_dynamic_ids = self._publish_learned_dynamics(learned)
        else:
            published_dynamic_ids = []
            published_dynamic_ids = self._publish_learned_dynamics(learned)
        else:
            published_dynamic_ids = []

        return WorldTaskResult.success(
            self.task_name,
            "song learning pass completed",
            credential_ok=credential_ok,
            learned=learned,
            abandoned=abandoned,
            awaiting=awaiting,
            dynamic_ids=published_dynamic_ids,
            dynamic_ids=published_dynamic_ids,
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

    def _publish_learned_dynamics(self, learned: list[str]) -> list[str]:
        if self.dynamic_capability is None:
            return []
        published: list[str] = []
        for song_name in learned:
            content = self._compose_learned_dynamic_content(song_name)
            try:
                ok, _, item = self.dynamic_capability.publish_agent_dynamic(
                    character_id=self.character_id,
                    content=content,
                    source_type="song_learned",
                    source_id=song_name,
                    visibility="global",
                    allow_comment=True,
                )
                if ok and item is not None:
                    published.append(item["id"])
            except Exception as exc:
                self.logger.warning(f"Failed to publish learned-song dynamic for {song_name}: {exc}")
        return published

    def _build_learned_dynamic_content(self, song_name: str) -> str:
        return f"今天学会了《{song_name}》。之后如果你想听，我就可以唱给你听啦。"

    def _compose_learned_dynamic_content(self, song_name: str) -> str:
        fallback = self._build_learned_dynamic_content(song_name)
        if self.dynamic_capability is None:
            return fallback

        instruction = (
            "这是一次学歌成功后的角色动态。"
            "请以角色的第一人称视角，表达学会一首新歌后的开心，对这首歌的感受"
            "以及想唱给用户听的心情，语气活泼可爱。"
        )
        structured_context = "\n".join(
            [
                f"角色名：{self.character_name}",
                f"新学会的歌曲：{song_name}",
            ]
        )
        try:
            result = asyncio.run(
                self.dynamic_capability.generate_world_dynamic_content(
                    dynamic_type="song_learned",
                    instruction=instruction,
                    structured_context=structured_context,
                )
            )
            return result or fallback
        except Exception as exc:
            self.logger.warning(f"Learned-song dynamic composer failed, fallback to template text: {exc}")
            return fallback

