from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.world.types.task_result import WorldTaskResult
from src.world.types.world_task import WorldTask

if TYPE_CHECKING:
    from src.system.system_runtime import SystemRuntime


class ProactiveTopicCheckTask(WorldTask):
    task_name = "proactive_topic_check"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(self.task_name, config)
        self.system_runtime: SystemRuntime | None = None

    def initialize(self, system_runtime: SystemRuntime) -> None:
        self.system_runtime = system_runtime

    def ensure_dependencies(self) -> None:
        """检查主动话题检查任务依赖。"""
        super().ensure_dependencies()
        if self.system_runtime is None:
            raise RuntimeError("ProactiveTopicCheckTask dependency is missing: system_runtime")

    async def run_once(self) -> WorldTaskResult:
        if self.system_runtime is None:
            return WorldTaskResult.skipped_result(self.task_name, "system runtime is unavailable")
        stage_manager = self.system_runtime.stage_manager
        if stage_manager is None:
            return WorldTaskResult.skipped_result(self.task_name, "stage manager is unavailable")
        sent = await stage_manager.scan_due_events()
        return WorldTaskResult.success(self.task_name, f"woke chat stages; dispatched={sent}")
