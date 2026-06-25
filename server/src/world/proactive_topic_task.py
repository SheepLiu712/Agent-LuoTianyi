from __future__ import annotations

from typing import Any, Dict

from src.world.types.task_result import WorldTaskResult
from src.world.types.world_task import WorldTask


class ProactiveTopicCheckTask(WorldTask):
    task_name = "proactive_topic_check"

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        super().__init__(self.task_name, config)
        self.system_runtime: Any | None = None

    def initialize(self, system_runtime: Any) -> None:
        self.system_runtime = system_runtime

    async def run_once(self) -> WorldTaskResult:
        if self.system_runtime is None:
            return WorldTaskResult.skipped_result(self.task_name, "system runtime is unavailable")
        await self.system_runtime.chat_session_manager.proactive_topic_maker.run_periodic_checks(
            self.system_runtime
        )
        return WorldTaskResult.success(self.task_name, "proactive topic check completed")
