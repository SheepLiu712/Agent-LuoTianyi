from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.world.types.task_result import WorldTaskResult
from src.world.types.world_task import WorldTask

if TYPE_CHECKING:
    from src.server_runtime import ServerRuntime


class ProactiveTopicCheckTask(WorldTask):
    task_name = "proactive_topic_check"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(self.task_name, config)
        self.server_runtime: ServerRuntime | None = None

    def initialize(self, server_runtime: ServerRuntime) -> None:
        self.server_runtime = server_runtime

    def ensure_dependencies(self) -> None:
        """检查主动话题检查任务依赖。"""
        super().ensure_dependencies()
        if self.server_runtime is None:
            raise RuntimeError("ProactiveTopicCheckTask dependency is missing: server_runtime")

    async def run_once(self) -> WorldTaskResult:
        if self.server_runtime is None:
            return WorldTaskResult.skipped_result(self.task_name, "system runtime is unavailable")
        stage_manager = self.server_runtime.stage_manager
        if stage_manager is None:
            return WorldTaskResult.skipped_result(self.task_name, "stage manager is unavailable")
        sent = await stage_manager.scan_due_events()
        return WorldTaskResult.success(self.task_name, f"woke chat stages; dispatched={sent}")
