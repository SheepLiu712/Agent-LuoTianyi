from __future__ import annotations

from typing import Any, Dict

from src.world.types.task_result import WorldTaskResult
from src.world.types.world_task import WorldTask


class ExpiredEventCleanupTask(WorldTask):
    task_name = "purge_expired_events"

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        super().__init__(self.task_name, config)
        self.event_store: Any | None = None

    def initialize(self, system_runtime: Any) -> None:
        database_manager = getattr(system_runtime, "database_manager", None)
        self.event_store = getattr(database_manager, "event_store", None)

    def run_once(self) -> WorldTaskResult:
        if self.event_store is None:
            return WorldTaskResult.skipped_result(self.task_name, "event store is unavailable")
        purged = self.event_store.purge_expired_events()
        return WorldTaskResult.success(
            self.task_name,
            "expired events purged",
            purged=purged,
        )
