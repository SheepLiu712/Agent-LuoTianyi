from __future__ import annotations

import asyncio
import json
import random
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, TYPE_CHECKING

from src.system.database.event_models import UnifiedEventType
from src.utils.logger import get_logger
from src.world.citywalk.errors import CitywalkError
from src.world.types.task_result import WorldTaskResult
from src.world.types.world_task import WorldTask

if TYPE_CHECKING:
    from src.system.database import DatabaseManager
    from src.system.database.services.event_store import EventStore
    from src.system.system_runtime import SystemRuntime
    from src.agent_runtime.character_runtime import CharacterRuntime


class CitywalkTask(WorldTask):
    base_task_name = "try_citywalk"

    def __init__(self, config: Dict[str, Any] | None = None, character_id: str = "luotianyi") -> None:
        self.character_id = character_id
        super().__init__(f"{self.base_task_name}:{character_id}", config)
        self.logger = get_logger(__name__)
        self.system_runtime: "SystemRuntime" | None = None
        self.database_manager: "DatabaseManager" | None = None
        self.event_store: "EventStore" | None = None
        self.character_runtime: "CharacterRuntime" | None = None
        self.citywalk_service: Any | None = None

    def initialize(self, system_runtime: "SystemRuntime") -> None:
        self.system_runtime = system_runtime
        self.database_manager = getattr(system_runtime, "database_manager", None)
        self.event_store = getattr(self.database_manager, "event_store", None)
        agent_runtime = getattr(system_runtime, "agent_runtime", None)
        self.character_runtime = agent_runtime.get_character_runtime(self.character_id) if agent_runtime is not None else None
        self.citywalk_service = self._build_citywalk_service()

    def ensure_dependencies(self) -> None:
        """检查 citywalk 任务的基础依赖。"""
        super().ensure_dependencies()
        required = {
            "system_runtime": self.system_runtime,
            "database_manager": self.database_manager,
            "event_store": self.event_store,
            "character_runtime": self.character_runtime,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise RuntimeError(f"CitywalkTask dependencies are missing: {', '.join(missing)}")

    def run_once(self) -> WorldTaskResult:
        if self.citywalk_service is None:
            return WorldTaskResult.skipped_result(self.task_name, "citywalk service is unavailable")

        should_run, probability, sample = self._sample_daily_run()
        if not should_run:
            self.logger.info(
                "Citywalk daily sample skipped: sample=%.4f probability=%.4f",
                sample,
                probability,
            )
            return WorldTaskResult.skipped_result(
                self.task_name,
                "citywalk daily sample skipped",
                sample=sample,
                probability=probability,
            )

        try:
            output_path = self.citywalk_service.run_once()
        except CitywalkError as exc:
            self.logger.warning(f"Citywalk skipped due to runtime error: {exc}")
            return WorldTaskResult.skipped_result(
                self.task_name,
                "citywalk runtime error",
                error=str(exc),
            )
        if not output_path:
            return WorldTaskResult.skipped_result(self.task_name, "citywalk did not produce a diary")

        overview = self._normalize_overview(output_path)
        if self.event_store is not None:
            character_name = self._character_display_name()
            asyncio.run(
                self.event_store.add_event(
                    {
                        "character": self.character_id,
                        "title": f"{character_name}出门散步",
                        "description": overview,
                        "event_type": UnifiedEventType.TRAVEL.value,
                        "start_datetime": datetime.now(),
                        "is_recurring": False,
                        "source": "world_citywalk",
                    }
                )
            )
        dynamic_id = self._publish_citywalk_dynamic(output_path)
        return WorldTaskResult.success(
            self.task_name,
            "citywalk completed",
            output_path=str(output_path),
            dynamic_id=dynamic_id,
        )

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

        json_module = llm_service.register_llm_module(f"{self.character_id}_citywalk_json", json_cfg)
        text_module = llm_service.register_llm_module(f"{self.character_id}_citywalk_text", text_cfg)
        try:
            vlm_module = llm_service.register_vlm_module(f"{self.character_id}_citywalk_vlm", vlm_cfg)
        except Exception as exc:
            self.logger.warning(f"Citywalk VLM module unavailable: {exc}")
            vlm_module = None
        return CitywalkLLMModules(json_module=json_module, text_module=text_module, vlm_module=vlm_module)

    @staticmethod
    def _normalize_overview(output_path: Path) -> str:
        text = str(output_path)
        if text.endswith(".md"):
            return f"今天写了一篇散步日记：{text}"
        return text

    def _publish_citywalk_dynamic(self, output_path: Path) -> str | None:
        if self.character_runtime is None:
            return None
        try:
            report = self._load_citywalk_report(output_path)
            result = asyncio.run(
                self.character_runtime.publish_citywalk_dynamic(
                    report=report,
                    source_id=str(output_path),
                )
            )
            content = str(result.get("content") or "").strip()
            dynamic_id = result.get("dynamic_id")
            if content:
                self._write_dynamic_content_to_report(output_path, content, dynamic_id)
            if dynamic_id:
                return str(dynamic_id)
        except Exception as exc:
            self.logger.warning(f"Failed to publish citywalk dynamic: {exc}")
        return None

    @staticmethod
    def _load_citywalk_report(output_path: Any) -> dict[str, Any]:
        path = Path(str(output_path))
        if not path.is_file():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    @staticmethod
    def _write_dynamic_content_to_report(output_path: Any, content: str, dynamic_id: Any = None) -> None:
        path = Path(str(output_path))
        if not path.is_file():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return
            data["diary_text"] = content
            data["dynamic_content"] = content
            if dynamic_id:
                data["dynamic_id"] = str(dynamic_id)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            get_logger(__name__).warning(f"Failed to write citywalk dynamic content back to report: {exc}")

    def _sample_daily_run(self) -> tuple[bool, float, float]:
        raw_probability = self.config.get("daily_run_probability", 0.1)
        try:
            probability = float(raw_probability)
        except (TypeError, ValueError):
            probability = 0.1
        probability = max(0.0, min(1.0, probability))
        sample = random.random()
        return sample < probability, probability, sample

    def _character_display_name(self) -> str:
        profile = getattr(self.character_runtime, "profile", None)
        return str(getattr(profile, "display_name", None) or self.character_id)
