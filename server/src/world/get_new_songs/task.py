from __future__ import annotations

from typing import Any, Dict, TYPE_CHECKING

from src.utils.logger import get_logger
from src.world.types.task_result import WorldTaskResult
from src.world.types.world_task import WorldTask
from src.world.get_new_songs.daily_new_song_fetcher import sync_daily_new_songs
if TYPE_CHECKING:
    from src.system.system_runtime import SystemRuntime


class VCPediaNewSongTask(WorldTask):
    task_name = "sync_new_song_knowledge"

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        super().__init__(self.task_name, config)
        self.logger = get_logger(__name__)
        self.llm_module: Any | None = None

    def initialize(self, system_runtime: "SystemRuntime") -> None:
        crawler_cfg = self.config.get("crawler", {})
        module_cfg = crawler_cfg.get("llm_module")
        llm_service = system_runtime.llm_service
        if module_cfg and llm_service is not None:
            self.llm_module = llm_service.register_llm_module("song_knowledge_crawler", module_cfg)

    def run_once(self) -> WorldTaskResult:
        try:
            result = sync_daily_new_songs(self.config, llm_module=self.llm_module)
        except Exception as exc:
            self.logger.warning(f"VCPedia new song sync failed: {exc}")
            return WorldTaskResult.failure(self.task_name, str(exc))

        added = result.get("added", [])
        failed = result.get("failed", [])
        return WorldTaskResult.success(
            self.task_name,
            "new song knowledge sync completed",
            added_count=len(added),
            added=added,
            failed_count=len(failed),
            failed=failed
        )
