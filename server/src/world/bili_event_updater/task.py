from __future__ import annotations

from typing import Any, Dict, TYPE_CHECKING, Optional

from src.utils.logger import get_logger
from src.world.bili_event_updater import BiliEventUpdater
from src.world.types.task_result import WorldTaskResult
from src.world.types.world_task import WorldTask

if TYPE_CHECKING:
    from src.system.system_runtime import SystemRuntime


class BiliEventUpdateTask(WorldTask):
    task_name = "bili_event_update"

    def __init__(self, config: Dict[str, Any]) -> None:
        super().__init__(self.task_name, config)
        self.logger = get_logger(__name__)
        self.system_runtime: "SystemRuntime" | None = None
        self.updater: Optional[BiliEventUpdater] = None

    def initialize(self, system_runtime: "SystemRuntime") -> None:
        self.system_runtime = system_runtime
        event_store = system_runtime.database_manager.event_store
        llm_service = system_runtime.llm_service
        llm_module = None
        vlm_module = None
        if llm_service is not None:
            llm_cfg = self.config.get("llm_module")
            vlm_cfg = self.config.get("vlm_module")
            if llm_cfg:
                llm_module = llm_service.register_llm_module("bili_event_parser", llm_cfg)
            if vlm_cfg:
                vlm_module = llm_service.register_vlm_module("bili_event_parser", vlm_cfg)
        self.updater = BiliEventUpdater(
            config=self.config,
            event_store=event_store,
            llm_module=llm_module,
            vlm_module=vlm_module,
        )

    def ensure_dependencies(self) -> None:
        """检查 B 站事件更新任务依赖。"""
        super().ensure_dependencies()
        required = {
            "system_runtime": self.system_runtime,
            "updater": self.updater,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise RuntimeError(f"BiliEventUpdateTask dependencies are missing: {', '.join(missing)}")

    async def run_once(self) -> WorldTaskResult:
        if self.updater is None:
            return WorldTaskResult.skipped_result(self.task_name, "BiliEventUpdater is unavailable")
        try:
            result = await self.updater.fetch_and_update_events()
            return WorldTaskResult.success(self.task_name, "bilibili dynamics synced", **result)
        except Exception as e:
            self.logger.error(f"Error during BiliEventUpdater run_once {e}")
            return WorldTaskResult.failure(self.task_name, f"Error: {e}")
