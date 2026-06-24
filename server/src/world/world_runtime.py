from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from src.system.database.event_models import UnifiedEventType
from src.utils.logger import get_logger
from src.world.activity_context_provider import ActivityContextProvider
from src.world.bili_event_updater import BiliEventUpdater
from src.world.daily_tasks import WorldDailyTasks
from src.world.world_clock import WorldClock

if TYPE_CHECKING:
    from src.capabilities import CapabilityManager
    from src.system.database.event_store import EventStore
    from src.system.database import DatabaseManager
    from src.system.system_runtime import SystemRuntime
    from src.utils.llm_service import LLMService


class WorldRuntime:
    """Owns world-facing services and the world clock."""

    def __init__(
        self,
        config: Dict[str, Any],
        llm_service: "LLMService",
        database_manager: "DatabaseManager | None" = None,
        capability_manager: "CapabilityManager | None" = None,
        root_config: Dict[str, Any] | None = None,
    ) -> None:
        self.config = config or {}
        self.root_config = root_config or {}
        self.llm_service = llm_service
        self.database_manager = database_manager
        self.capability_manager = capability_manager
        self.system_runtime: "SystemRuntime | None" = None
        self.logger = get_logger(__name__)

        bili_cfg = self._build_bili_event_config()
        self.event_store: "EventStore | None" = getattr(database_manager, "event_store", None)
        self.bili_event_updater = BiliEventUpdater(config=bili_cfg, event_store=self.event_store)
        if database_manager is not None:
            database_manager.set_event_store_llm_client(self.bili_event_updater.llm_client)

        self.context_provider: ActivityContextProvider | None = None
        if self.event_store is not None:
            self.context_provider = ActivityContextProvider(
                event_store=self.event_store,
                mention_cooldown_hours=bili_cfg.get("context", {}).get("mention_cooldown_hours", 6),
                lookahead_days=bili_cfg.get("context", {}).get("lookahead_days", 7),
                max_context_events=bili_cfg.get("context", {}).get("max_context_events", 5),
            )

        silence_cfg = bili_cfg.get("silence", {})
        self.silence_pre_minutes = silence_cfg.get("concert_pre_start_minutes", 60)
        self.silence_post_minutes = silence_cfg.get("concert_post_end_minutes", 30)
        self._silence_cache: Optional[Dict[str, Any]] = None
        self._silence_cache_ts: float = 0.0
        self._silence_cache_ttl: float = 60 * 60

        self.world_clock = WorldClock()
        self._daily_tasks: WorldDailyTasks | None = None
        self._startup_event_task: asyncio.Task | None = None
        self._clock_actions_registered = False

    def set_system_runtime(self, system_runtime: "SystemRuntime") -> None:
        self.system_runtime = system_runtime


    def register_clock_actions(self) -> None:
        self._register_clock_actions()

    def start_background_services(self) -> None:
        if self._startup_event_task is None or self._startup_event_task.done():
            self._startup_event_task = asyncio.create_task(self._initialize_event_store())
        self.world_clock.start()

    async def stop_background_services(self) -> None:
        await self.world_clock.stop()
        if self._startup_event_task is not None:
            self._startup_event_task.cancel()
            try:
                await self._startup_event_task
            except asyncio.CancelledError:
                pass
        self._startup_event_task = None

    async def _initialize_event_store(self) -> None:
        if self.event_store is None:
            return
        try:
            await self.event_store.ensure_holidays()
        except Exception as e:
            self.logger.warning(f"Failed to ensure holidays: {e}")

    def _register_clock_actions(self) -> None:
        if self._clock_actions_registered:
            return
        self._register_daily_4am_actions()
        if self.event_store is not None:
            self.world_clock.register_interval_action(
                "bili_event_update",
                interval_seconds=self.bili_event_updater.fetch_interval_seconds,
                action=self.bili_event_updater.fetch_and_update_events,
                run_immediately=True,
            )
        self.world_clock.register_interval_action(
            "proactive_topic_check",
            interval_seconds=10 * 60,
            action=self._run_proactive_topic_check,
        )
        self._clock_actions_registered = True

    def _register_daily_4am_actions(self) -> None:
        tasks = self._build_daily_tasks()
        if tasks is None:
            self.logger.info("World daily tasks are not configured; skipping 4am task registration")
            return
        self.world_clock.register_daily_action("purge_expired_events", 4, 0, tasks.purge_expired_events)
        self.world_clock.register_daily_action("refresh_bili_cookie", 4, 0, tasks.refresh_bili_cookie)
        self.world_clock.register_daily_action("try_citywalk", 4, 0, tasks.try_citywalk)
        self.world_clock.register_daily_action("sync_new_song_knowledge", 4, 0, tasks.sync_new_song_knowledge)
        self.world_clock.register_daily_action("check_qq_music_credential", 4, 0, tasks.check_qq_music_credential)
        self.world_clock.register_daily_action("learn_new_songs", 4, 0, tasks.learn_new_songs)


    async def _run_proactive_topic_check(self) -> None:
        if self.system_runtime is None:
            return
        await self.system_runtime.chat_session_manager.proactive_topic_maker.run_periodic_checks(
            self.system_runtime
        )

    def _build_bili_event_config(self) -> Dict[str, Any]:
        cfg: Dict[str, Any] = {}
        cfg.update(self.root_config.get("bili_dynamic_fetcher", {}))
        cfg.update(self.config.get("bili_event_updater", {}))
        proactive_cfg = self.root_config.get("chat_sessions", {}).get("proactive_topic_maker", {})
        for key in ("context", "silence"):
            if key in proactive_cfg and key not in cfg:
                cfg[key] = proactive_cfg[key]
        return cfg

    def _build_daily_tasks(self) -> WorldDailyTasks | None:
        if self.system_runtime is None or self.event_store is None:
            return None

        citywalk_service = self._build_citywalk_service()
        song_learner = self._get_auto_song_learner()
        song_knowledge_config = self.root_config.get("music", {}).get("song_knowledge", {})
        if citywalk_service is None and song_learner is None:
            self.logger.warning("World daily tasks have neither citywalk nor song learner service")

        return WorldDailyTasks(
            song_knowledge_config=song_knowledge_config,
            citywalk_service=citywalk_service,
            song_learner=song_learner,
            event_store=self.event_store,
        )

    def _build_citywalk_service(self) -> Any | None:
        try:
            from src.world.citywalk.runtime_scheduler import CitywalkRuntimeService

            vector_store = None
            if self.system_runtime is not None:
                try:
                    vector_store = getattr(self.system_runtime.agent._runtime_hub, "vector_store", None)
                except Exception:
                    vector_store = None
            if vector_store is None:
                self.logger.warning("Citywalk service skipped: vector store is not available")
                return None
            return CitywalkRuntimeService(self.config.get("citywalk", {}), vector_store)
        except Exception as e:
            self.logger.warning(f"Citywalk service skipped: {e}")
            return None

    def _get_auto_song_learner(self) -> Any | None:
        try:
            return self.capability_manager.singing.music_manager.auto_song_learner
        except Exception:
            return None
