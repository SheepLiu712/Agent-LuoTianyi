from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict

from src.system.database.event_models import UnifiedEventType
from src.utils.logger import get_logger
from src.world.types.task_result import WorldTaskResult
from src.world.types.world_task import WorldTask


class CitywalkTask(WorldTask):
    task_name = "try_citywalk"

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        super().__init__(self.task_name, config)
        self.logger = get_logger(__name__)
        self.system_runtime: Any | None = None
        self.database_manager: Any | None = None
        self.event_store: Any | None = None
        self.citywalk_service: Any | None = None

    def initialize(self, system_runtime: Any) -> None:
        self.system_runtime = system_runtime
        self.database_manager = getattr(system_runtime, "database_manager", None)
        self.event_store = getattr(self.database_manager, "event_store", None)
        self.citywalk_service = self._build_citywalk_service()

    def run_once(self) -> WorldTaskResult:
        if self.citywalk_service is None:
            return WorldTaskResult.skipped_result(self.task_name, "citywalk service is unavailable")

        output_path = self.citywalk_service.run_once()
        if not output_path:
            return WorldTaskResult.skipped_result(self.task_name, "citywalk did not produce a diary")

        overview = self._normalize_overview(output_path)
        if self.event_store is not None:
            asyncio.run(
                self.event_store.add_event(
                    {
                        "title": "洛天依出门散步",
                        "description": overview,
                        "event_type": UnifiedEventType.TRAVEL.value,
                        "start_datetime": datetime.now(),
                        "is_recurring": False,
                        "source": "world_citywalk",
                    }
                )
            )
        return WorldTaskResult.success(self.task_name, "citywalk completed", output_path=str(output_path))

    def _build_citywalk_service(self) -> Any | None:
        if self.system_runtime is None:
            return None
        try:
            from src.world.citywalk.llm_modules import CitywalkLLMModules
            from src.world.citywalk.runtime_scheduler import CitywalkRuntimeService

            agent_runtime = getattr(self.system_runtime, "agent_runtime", None)
            vector_store = getattr(agent_runtime, "vector_store", None)
            if vector_store is None:
                self.logger.warning("Citywalk task skipped: vector store is unavailable.")
                return None
            llm_modules = self._build_llm_modules()
            return CitywalkRuntimeService(self.config, vector_store, llm_client=llm_modules)
        except Exception as exc:
            self.logger.warning(f"Citywalk task initialization skipped: {exc}")
            return None

    def _build_llm_modules(self) -> Any:
        from src.world.citywalk.llm_modules import CitywalkLLMModules

        llm_service = getattr(self.system_runtime, "llm_service", None)
        if llm_service is None:
            return None

        modules_cfg = self.config.get("llm_modules", {})
        decision_llm_cfg = dict(self.config.get("decision", {}).get("llm", {}))
        model_name = decision_llm_cfg.get("name") or decision_llm_cfg.get("model") or "qwen3.5-plus"
        decision_llm_cfg["name"] = model_name
        decision_llm_cfg.pop("model", None)

        json_cfg = modules_cfg.get("json") or {
            "llm": {**decision_llm_cfg, "enable_thinking": False, "use_json": True},
            "prompt_name": "citywalk_llm_prompt",
        }
        text_cfg = modules_cfg.get("text") or {
            "llm": {**decision_llm_cfg, "enable_thinking": False, "use_json": False},
            "prompt_name": "citywalk_llm_prompt",
        }
        vlm_cfg = modules_cfg.get("vlm") or {
            "vlm": {"name": "qwen3-vl-plus"},
            "prompt_name": "citywalk_vlm_prompt",
        }

        json_module = llm_service.register_llm_module("citywalk_json", json_cfg)
        text_module = llm_service.register_llm_module("citywalk_text", text_cfg)
        try:
            vlm_module = llm_service.register_vlm_module("citywalk_vlm", vlm_cfg)
        except Exception as exc:
            self.logger.warning(f"Citywalk VLM module unavailable: {exc}")
            vlm_module = None
        return CitywalkLLMModules(json_module=json_module, text_module=text_module, vlm_module=vlm_module)

    @staticmethod
    def _normalize_overview(output_path: Any) -> str:
        text = str(output_path)
        if text.endswith(".md"):
            return f"今天写了一篇散步日记：{text}"
        return text
