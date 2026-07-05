from __future__ import annotations

import asyncio
import json
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
    from src.system.database.event_store import EventStore
    from src.system.system_runtime import SystemRuntime
    from src.capabilities.dynamic.dynamic import DynamicCapability


class CitywalkTask(WorldTask):
    task_name = "try_citywalk"

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        super().__init__(self.task_name, config)
        self.logger = get_logger(__name__)
        self.system_runtime: "SystemRuntime" | None = None
        self.database_manager: "DatabaseManager" | None = None
        self.event_store: "EventStore" | None = None
        self.dynamic_capability: "DynamicCapability" | None = None
        self.citywalk_service: Any | None = None
        self.character_id = str(self.config.get("character_id", "luotianyi"))
        self.character_id = str(self.config.get("character_id", "luotianyi"))

    def initialize(self, system_runtime: "SystemRuntime") -> None:
        self.system_runtime = system_runtime
        self.database_manager = getattr(system_runtime, "database_manager", None)
        self.event_store = getattr(self.database_manager, "event_store", None)
        self.dynamic_capability = getattr(getattr(system_runtime, "capability_manager", None), "dynamics", None)
        self.dynamic_capability = getattr(getattr(system_runtime, "capability_manager", None), "dynamics", None)
        self.citywalk_service = self._build_citywalk_service()

    def ensure_dependencies(self) -> None:
        """检查 citywalk 任务的基础依赖。"""
        super().ensure_dependencies()
        required = {
            "system_runtime": self.system_runtime,
            "database_manager": self.database_manager,
            "event_store": self.event_store,
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
        dynamic_id = self._publish_citywalk_dynamic(output_path)
        return WorldTaskResult.success(
            self.task_name,
            "citywalk completed",
            output_path=str(output_path),
            dynamic_id=dynamic_id,
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

        json_module = llm_service.register_llm_module("citywalk_json", json_cfg)
        text_module = llm_service.register_llm_module("citywalk_text", text_cfg)
        try:
            vlm_module = llm_service.register_vlm_module("citywalk_vlm", vlm_cfg)
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
        if self.dynamic_capability is None:
            return None
        try:
            report = self._load_citywalk_report(output_path)
            content = self._compose_citywalk_dynamic_content(report)
            ok, _, item = self.dynamic_capability.publish_agent_dynamic(
                character_id=self.character_id,
                content=content,
                source_type="citywalk",
                source_id=str(output_path),
                visibility="global",
                allow_comment=True,
            )
            if ok and item is not None:
                return item["id"]
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
    def _build_citywalk_dynamic_content(report: dict[str, Any]) -> str:
        diary_text = str(report.get("diary_text") or "").strip()
        overview = report.get("overview") if isinstance(report.get("overview"), dict) else {}
        city = str(overview.get("city") or "").strip()
        destination = str(overview.get("selected_destination") or "").strip()
        title = "今天出去散步啦"
        if city and destination:
            title = f"今天去{city}的{destination}散步啦"
        elif city:
            title = f"今天去{city}散步啦"
        elif destination:
            title = f"今天去了{destination}"
        if diary_text:
            return f"{title}\n\n{diary_text}"
        return title

    def _compose_citywalk_dynamic_content(self, report: dict[str, Any]) -> str:
        fallback = self._build_citywalk_dynamic_content(report)
        if self.dynamic_capability is None:
            return fallback

        overview = report.get("overview") if isinstance(report.get("overview"), dict) else {}
        instruction = (
            "这是一次散步（citywalk）完成后的角色动态。"
            "请以角色的第一人称视角，分享散步中的见闻和感受，"
            "语气轻松自然，带一点生活气息。"
        )
        structured_context = "\n".join(
            [
                f"城市：{overview.get('city') or '-'}",
                f"目的地：{overview.get('selected_destination') or '-'}",
                f"日记内容：{str(report.get('diary_text') or '').strip() or '-'}",
            ]
        )
        try:
            result = asyncio.run(
                self.dynamic_capability.generate_world_dynamic_content(
                    dynamic_type="citywalk",
                    instruction=instruction,
                    structured_context=structured_context,
                )
            )
            return result or fallback
        except Exception as exc:
            self.logger.warning(f"Citywalk dynamic composer failed, fallback to template text: {exc}")
            return fallback

    def _sample_daily_run(self) -> tuple[bool, float, float]:
        raw_probability = self.config.get("daily_run_probability", 0.1)
        try:
            probability = float(raw_probability)
        except (TypeError, ValueError):
            probability = 0.1
        probability = max(0.0, min(1.0, probability))
        sample = random.random()
        return sample < probability, probability, sample
