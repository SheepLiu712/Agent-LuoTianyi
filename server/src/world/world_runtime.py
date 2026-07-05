from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from src.world.bili_event_updater.task import BiliEventUpdateTask
from src.world.citywalk.task import CitywalkTask
from src.world.dynamic_interaction.task import DynamicInteractionTask
from src.world.event_cleanup_task import ExpiredEventCleanupTask
from src.world.get_new_songs.task import VCPediaNewSongTask
from src.world.learn_sing_songs.task import LearnSingSongsTask
from src.world.proactive_topic_task import ProactiveTopicCheckTask
from src.world.world_clock import WorldClock
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.system.system_runtime import SystemRuntime
    from src.world.types.world_task import WorldTask


class WorldRuntime:
    """Owns world-facing services and the world clock."""

    def __init__(
        self,
        config: Dict[str, Any],
    ) -> None:
        self.config = config or {}
        self.system_runtime: "SystemRuntime | None" = None
        self.logger = get_logger(__name__)

        self.world_clock = WorldClock()
        self.citywalk_task: CitywalkTask | None = None
        self.citywalk_tasks: List[CitywalkTask] = []
        self.learn_sing_songs_task: LearnSingSongsTask | None = None
        self.learn_sing_songs_tasks: List[LearnSingSongsTask] = []
        self.vcpedia_new_song_task: VCPediaNewSongTask | None = None
        self.bili_event_update_task: BiliEventUpdateTask | None = None
        self.bili_event_update_tasks: List[BiliEventUpdateTask] = []
        self.dynamic_interaction_task: DynamicInteractionTask | None = None
        self.proactive_topic_check_task: ProactiveTopicCheckTask | None = None
        self.expired_event_cleanup_task: ExpiredEventCleanupTask | None = None
        self.tasks: List["WorldTask"] = []
        self._startup_event_task: asyncio.Task | None = None
        self._modules_initialized = False

    def set_system_runtime(self, system_runtime: "SystemRuntime") -> None:
        self.system_runtime = system_runtime

    def wire_dependencies(self, *, system_runtime: "SystemRuntime") -> None:
        """向世界运行时和任务模块派发系统依赖。"""
        self.set_system_runtime(system_runtime)
        self.initialize_modules()
        self.ensure_dependencies()

    def initialize_modules(self) -> None:
        if self._modules_initialized:
            return
        if self.system_runtime is None:
            raise RuntimeError("WorldRuntime requires system_runtime before module initialization.")

        self.citywalk_tasks = self._build_citywalk_tasks()
        self.citywalk_task = self.citywalk_tasks[0] if self.citywalk_tasks else None
        self.learn_sing_songs_tasks = self._build_learn_sing_songs_tasks()
        self.learn_sing_songs_task = (
            self.learn_sing_songs_tasks[0] if self.learn_sing_songs_tasks else None
        )
        self.vcpedia_new_song_task = VCPediaNewSongTask(self.config.get("song_knowledge", {}))
        self.bili_event_update_tasks = self._build_bili_event_update_tasks()
        self.bili_event_update_task = self.bili_event_update_tasks[0] if self.bili_event_update_tasks else None
        self.dynamic_interaction_task = (
            DynamicInteractionTask(
                self._character_task_config("dynamic_interaction", self._default_character_id())
            )
            if self._task_enabled("dynamic_interaction")
            else None
        )
        self.proactive_topic_check_task = ProactiveTopicCheckTask(
            self.config.get("proactive_topic_check", {})
        )
        self.expired_event_cleanup_task = ExpiredEventCleanupTask(
            self.config.get("expired_event_cleanup", {})
        )

        self.tasks: List["WorldTask"] = [
            *self.citywalk_tasks,
            *self.learn_sing_songs_tasks,
            self.vcpedia_new_song_task,
            *self.bili_event_update_tasks,
            self.dynamic_interaction_task,
            self.proactive_topic_check_task,
            self.expired_event_cleanup_task,
        ]
        self.tasks = [task for task in self.tasks if task is not None]
        for task in self.tasks:
            task.initialize(self.system_runtime)
            if hasattr(task, "ensure_dependencies"):
                task.ensure_dependencies()

        self._register_clock_actions()
        self._modules_initialized = True

    def start_background_services(self) -> None:
        if not self._modules_initialized:
            self.initialize_modules()
        self.ensure_dependencies()
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

    def ensure_dependencies(self) -> None:
        """检查世界运行时和任务模块依赖已经初始化。"""
        required = {
            "system_runtime": self.system_runtime,
            "world_clock": self.world_clock,
            "tasks": self.tasks,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise RuntimeError(f"WorldRuntime dependencies are missing: {', '.join(missing)}")
        if not self._modules_initialized:
            raise RuntimeError("WorldRuntime dependencies are missing: initialized modules")
        if not self.tasks:
            raise RuntimeError("WorldRuntime dependency is missing: tasks")
        for task in self.tasks:
            if task is None:
                raise RuntimeError("WorldRuntime dependency is missing: task")
            if hasattr(task, "ensure_dependencies"):
                task.ensure_dependencies()

    async def _initialize_event_store(self) -> None:
        if self.system_runtime is None:
            return
        try:
            await self.system_runtime.database_manager.event_store.ensure_holidays()
        except Exception as exc:
            self.logger.warning(f"Failed to ensure holidays: {exc}")

    def _register_clock_actions(self) -> None:
        for task in self.tasks:
            task_type = task.get_task_type()
            params = task.get_task_params()
            task_name = task.get_task_name()
            if task_type == "daily":
                self.world_clock.register_daily_action(
                    task_name,
                    params.get("hour", 0),
                    params.get("minute", 0),
                    task.run_once,
                )
            elif task_type == "interval":
                self.world_clock.register_interval_action(
                    task_name,
                    interval_seconds=params.get("interval_seconds", 60),
                    action=task.run_once,
                    run_immediately=params.get("run_immediately", False),
                )
            else:
                self.logger.warning(f"Unknown world clock task type for {task_name}: {task_type}")

    def _build_citywalk_tasks(self) -> List[CitywalkTask]:
        if not self._task_enabled("citywalk"):
            return []
        tasks: list[CitywalkTask] = []
        for character_id in self._character_ids():
            config = self._character_task_config("citywalk", character_id)
            if not config.get("enabled", True):
                continue
            tasks.append(CitywalkTask(config, character_id=character_id))
        return tasks

    def _build_learn_sing_songs_tasks(self) -> List[LearnSingSongsTask]:
        if not self._task_enabled("auto_song_learner"):
            return []
        if self.system_runtime is None:
            return []
        singing = getattr(getattr(self.system_runtime, "capability_manager", None), "singing", None)
        managers = getattr(singing, "singing_manager", None) or {}
        if not managers:
            self.logger.warning("No singing managers available; learn_sing_songs tasks skipped")
            return []
        config = self.config.get("auto_song_learner", {})
        tasks: list[LearnSingSongsTask] = []
        for character_id, singing_manager in managers.items():
            task_config = self._character_task_config("auto_song_learner", character_id, base_config=config)
            if not task_config.get("enabled", True):
                continue
            tasks.append(
                LearnSingSongsTask(
                    task_config,
                    character_id=character_id,
                    singing_manager=singing_manager,
                )
            )
        return tasks

    def _build_bili_event_update_tasks(self) -> List[BiliEventUpdateTask]:
        if not self._task_enabled("bili_dynamic_fetcher"):
            return []
        config = self.config.get("bili_dynamic_fetcher", {})
        bili_uids = config.get("bilibili_uids")
        tasks: list[BiliEventUpdateTask] = []
        for character_id in self._character_ids():
            if isinstance(bili_uids, dict) and character_id not in bili_uids:
                continue
            task_config = self._character_task_config("bili_dynamic_fetcher", character_id, base_config=config)
            if not task_config.get("enabled", True):
                continue
            if isinstance(bili_uids, dict):
                task_config["bilibili_uids"] = {character_id: bili_uids[character_id]}
            tasks.append(BiliEventUpdateTask(task_config, character_id=character_id))
        return tasks

    def _character_ids(self) -> list[str]:
        agent_runtime = getattr(self.system_runtime, "agent_runtime", None)
        runtimes = getattr(agent_runtime, "character_runtimes", None)
        if isinstance(runtimes, dict) and runtimes:
            return [str(character_id) for character_id in runtimes.keys()]
        default_character_id = getattr(agent_runtime, "default_character_id", None)
        if default_character_id:
            return [str(default_character_id)]
        return ["luotianyi"]

    def _default_character_id(self) -> str:
        agent_runtime = getattr(self.system_runtime, "agent_runtime", None)
        default_character_id = getattr(agent_runtime, "default_character_id", None)
        if default_character_id:
            return str(default_character_id)
        character_ids = self._character_ids()
        return character_ids[0] if character_ids else "luotianyi"

    def _character_task_config(
        self,
        config_key: str,
        character_id: str,
        *,
        base_config: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        source = dict(base_config or self.config.get(config_key, {}) or {})
        character_overrides = source.pop("characters", None) or source.pop("per_character", None) or {}
        override = {}
        if isinstance(character_overrides, dict):
            raw_override = character_overrides.get(character_id, {})
            if isinstance(raw_override, dict):
                override = raw_override
        merged = {**source, **override}
        merged["character_id"] = character_id
        return merged

    def _task_enabled(self, config_key: str) -> bool:
        cfg = self.config.get(config_key, {})
        return bool(cfg.get("enabled", True))
