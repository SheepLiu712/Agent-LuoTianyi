from __future__ import annotations

import json
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import src.domain.agent as d
from src.infrastructure.persistence.database.event_models import UnifiedEventType
from src.utils.logger import get_logger
from src.world.citywalk.errors import CitywalkError
from src.world.types.task_result import WorldTaskResult
from src.world.types.world_task import WorldTask

if TYPE_CHECKING:
    from src.stage.world_stage import WorldStage
    from src.infrastructure.persistence.database import DatabaseManager
    from src.infrastructure.persistence.database.services.event_store import EventStore
    from src.server_runtime import ServerRuntime
    from src.world.world_settlements import (
        FactHandlingOutcome,
        FactPlanOutcome,
        WorldSettlementRouter,
    )

CITYWALK_OBSERVATION_KIND = "citywalk_completed"


class CitywalkReportWriteBack:
    """把已发布动态的身份与正文写回散步报告。

    发布失败只记录日志，不撤销已完成的散步事实与报告。
    """

    def __init__(self, output_path: Path) -> None:
        self._path = Path(output_path)
        self._logger = get_logger(__name__)

    def on_fact_handled(self, outcome: FactHandlingOutcome) -> None:
        """处理结算：只记录失败，不修改报告。"""
        if outcome.request_status is d.HandlingRequestStatus.FAILED:
            self._logger.warning(
                "citywalk 事实处理失败 fact=%s code=%s", outcome.stimulus_id, outcome.error_code,
            )

    def on_fact_plan_executed(self, outcome: FactPlanOutcome) -> None:
        """执行结算：按已提交的动态效果回写正文与动态 ID。"""
        effect = next(
            (item for item in outcome.effect_refs if item.kind is d.EffectKind.DYNAMIC_POST), None,
        )
        if effect is None:
            self._logger.warning("citywalk 计划未提交动态效果 fact=%s", outcome.stimulus_id)
            return
        body = next(
            (action.body for action in outcome.plan.actions if isinstance(action, d.PublishDynamic)), "",
        )
        CitywalkTask._write_dynamic_content_to_report(self._path, body, effect.effect_id)


class CitywalkTask(WorldTask):
    base_task_name = "try_citywalk"

    def __init__(
        self, config: dict[str, Any] | None = None, character_id: str = "luotianyi",
        settlements: WorldSettlementRouter | None = None,
    ) -> None:
        self.character_id = character_id
        super().__init__(f"{self.base_task_name}:{character_id}", config)
        self.logger = get_logger(__name__)
        self.server_runtime: ServerRuntime | None = None
        self.database_manager: DatabaseManager | None = None
        self.event_store: EventStore | None = None
        self.citywalk_service: Any | None = None
        self.settlements = settlements
        self.character_name = str(self.config.get("character_name", "洛天依"))

    def initialize(self, server_runtime: ServerRuntime) -> None:
        self.server_runtime = server_runtime
        self.database_manager = getattr(server_runtime, "database_manager", None)
        self.event_store = getattr(self.database_manager, "event_store", None)
        self.citywalk_service = self._build_citywalk_service()

    def ensure_dependencies(self) -> None:
        """检查 citywalk 任务的基础依赖。"""
        super().ensure_dependencies()
        required = {
            "server_runtime": self.server_runtime,
            "database_manager": self.database_manager,
            "event_store": self.event_store,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise RuntimeError(f"CitywalkTask dependencies are missing: {', '.join(missing)}")

    async def run_once(self) -> WorldTaskResult:
        """抽样、执行散步并投递完成事实；本任务不生成动态正文、不调用角色能力。"""
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
            await self.event_store.add_event(
                {
                    "character": self.character_id,
                    "title": f"{self.character_name}出门散步",
                    "description": overview,
                    "event_type": UnifiedEventType.TRAVEL.value,
                    "start_datetime": datetime.now(),
                    "is_recurring": False,
                    "source": "world_citywalk",
                }
            )
        submitted = await self._submit_observation(output_path)
        return WorldTaskResult.success(
            self.task_name,
            "citywalk completed",
            output_path=str(output_path),
            observation_submitted=submitted,
        )

    async def _submit_observation(self, output_path: Any) -> bool:
        """把「散步完成」投递为世界观察事实，并登记发布回写。"""
        stage, character_id = await self._world_stage()
        if stage is None:
            self.logger.warning(f"WorldStage 不可用，散步事实未投递：{output_path}")
            return False
        path = Path(str(output_path))
        report = self._load_citywalk_report(path)
        fact = self._build_observation(character_id, path, report)
        subscriber = CitywalkReportWriteBack(path)
        if self.settlements is not None:
            self.settlements.register(fact.stimulus_id, subscriber)
        if await stage.fact_sink.submit(fact):
            return True
        if self.settlements is not None:
            self.settlements.discard(fact.stimulus_id)
        self.logger.warning(f"散步事实被 WorldStage 拒绝：{output_path}")
        return False

    async def _world_stage(self) -> tuple[WorldStage | None, str]:
        """取得本角色长期 WorldStage；运行时不支持时返回 None。"""
        server_runtime = self.server_runtime
        agent_runtime = getattr(server_runtime, "agent_runtime", None)
        character_id = str(getattr(agent_runtime, "default_character_id", None) or self.character_id)
        get_world_stage = getattr(server_runtime, "get_world_stage", None)
        if not callable(get_world_stage):
            return None, character_id
        return await get_world_stage(character_id), character_id

    def _build_observation(self, character_id: str, path: Path, report: dict[str, Any]) -> d.WorldObservation:
        """把报告规范化为不携带机械细节的世界事实。"""
        now = datetime.now(timezone.utc)
        return d.WorldObservation(
            stimulus_id=str(uuid4()),
            schema_version=1,
            occurred_at=now,
            source=d.StimulusSource.WORLD,
            target_character_ids=(character_id,),
            user_id=None,
            ephemeral=False,
            observation_kind=d.WorldObservationKind(value=CITYWALK_OBSERVATION_KIND),
            fact=d.WorldFact(fact_id=f"citywalk:{path}", summary=self.build_observation_summary(report)),
            evidence_refs=(),
            world_revision=int(now.timestamp()),
        )

    @staticmethod
    def build_observation_summary(report: dict[str, Any]) -> str:
        """优先使用报告自身的叙述，否则用目的地/经过地点/时长拼出简短摘要。"""
        narrative = str(report.get("diary_text") or "").strip()
        if narrative:
            return narrative
        overview = report.get("overview") if isinstance(report.get("overview"), dict) else {}
        places = [str(item) for item in (report.get("places") or []) if str(item).strip()]
        parts: list[str] = []
        destination = str(overview.get("selected_destination") or "").strip()
        if destination:
            parts.append(f"目的地：{destination}")
        if places:
            parts.append(f"经过：{'、'.join(places)}")
        duration = overview.get("total_duration_minutes")
        if duration:
            parts.append(f"时长：{duration}分钟")
        return "；".join(parts) or "完成了一次城市散步"

    def _build_citywalk_service(self) -> Any | None:
        if self.server_runtime is None:
            return None
        try:
            from src.world.citywalk.runtime_scheduler import CitywalkRuntimeService

            agent_runtime = getattr(self.server_runtime, "agent_runtime", None)
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

        llm_service = getattr(self.server_runtime, "llm_service", None)
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
