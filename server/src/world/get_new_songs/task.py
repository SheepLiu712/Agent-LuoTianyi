from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict
from uuid import uuid4

import src.domain.agent as d
from src.utils.logger import get_logger
from src.world.get_new_songs.daily_new_song_fetcher import (
    NewSongCandidate,
    collect_new_song_candidates,
    content_revision,
)
from src.world.types.task_result import WorldTaskResult
from src.world.types.world_task import WorldTask

if TYPE_CHECKING:
    from src.server_runtime import ServerRuntime
    from src.stage.world_stage import WorldStage

SONG_KNOWLEDGE_SOURCE = "vcpedia"
DEFAULT_CHARACTER_ID = "luotianyi"


class VCPediaNewSongTask(WorldTask):
    task_name = "sync_new_song_knowledge"

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        super().__init__(self.task_name, config)
        self.logger = get_logger(__name__)
        self.server_runtime: "ServerRuntime" | None = None
        self.llm_module: Any | None = None
        self.extraction_llm_module: Any | None = None

    def initialize(self, server_runtime: "ServerRuntime") -> None:
        self.server_runtime = server_runtime
        crawler_cfg = self.config.get("crawler", {})
        module_cfg = crawler_cfg.get("llm_module")
        extraction_cfg = crawler_cfg.get("extraction_llm_module")
        llm_service = server_runtime.llm_service
        if module_cfg and llm_service is not None:
            self.llm_module = llm_service.register_llm_module("song_knowledge_crawler", module_cfg)
        if extraction_cfg and llm_service is not None:
            self.extraction_llm_module = llm_service.register_llm_module(
                "song_knowledge_extractor", extraction_cfg
            )

    def ensure_dependencies(self) -> None:
        """检查新歌知识同步任务的基础依赖。"""
        super().ensure_dependencies()
        if getattr(self, "server_runtime", None) is None:
            raise RuntimeError("VCPediaNewSongTask dependency is missing: server_runtime")

    async def run_once(self) -> WorldTaskResult:
        """收集候选并投递为世界事实；本任务不写入知识。"""
        try:
            outcome = collect_new_song_candidates(
                self.config,
                llm_module=self.llm_module,
                extraction_llm_module=self.extraction_llm_module,
            )
        except Exception as exc:
            self.logger.warning(f"VCPedia new song sync failed: {exc}")
            return WorldTaskResult.failure(self.task_name, str(exc))

        candidates = outcome["discovered"]
        submitted, rejected = await self._submit_candidates(candidates)
        return WorldTaskResult.success(
            self.task_name,
            "new song knowledge candidates submitted",
            discovered_count=len(candidates),
            submitted_count=submitted,
            rejected_count=rejected,
            skipped_existing_count=len(outcome["skipped_existing"]),
            fetch_failed_count=len(outcome["fetch_failed"]),
            discovered=[candidate.song_name for candidate in candidates],
            skipped_existing=outcome["skipped_existing"],
            fetch_failed=outcome["fetch_failed"],
        )

    async def _submit_candidates(self, candidates: list[NewSongCandidate]) -> tuple[int, int]:
        """把候选逐条投递给 WorldStage，返回 (已受理数, 被拒数)。"""
        if not candidates:
            return 0, 0
        stage, character_id = await self._world_stage()
        if stage is None:
            self.logger.warning(
                "WorldStage 不可用，%d 首候选本次未投递：%s",
                len(candidates), "、".join(item.song_name for item in candidates),
            )
            return 0, len(candidates)

        submitted = 0
        rejected = 0
        for candidate in candidates:
            if await stage.fact_sink.submit(self._build_fact(character_id, candidate)):
                submitted += 1
            else:
                rejected += 1
                self.logger.warning(f"歌曲候选被 WorldStage 拒绝：{candidate.song_name}")
        return submitted, rejected

    async def _world_stage(self) -> tuple["WorldStage | None", str]:
        """取得本角色长期 WorldStage；运行时不支持时返回 None。"""
        server_runtime = self.server_runtime
        agent_runtime = getattr(server_runtime, "agent_runtime", None)
        character_id = str(getattr(agent_runtime, "default_character_id", None) or DEFAULT_CHARACTER_ID)
        get_world_stage = getattr(server_runtime, "get_world_stage", None)
        if not callable(get_world_stage):
            return None, character_id
        return await get_world_stage(character_id), character_id

    def _build_fact(self, character_id: str, candidate: NewSongCandidate) -> d.SongKnowledgeDiscovered:
        """把规范化候选包装成供应商无关的强类型世界事实。"""
        now = datetime.now(timezone.utc)
        return d.SongKnowledgeDiscovered(
            stimulus_id=str(uuid4()),
            schema_version=1,
            occurred_at=now,
            source=d.StimulusSource.WORLD,
            target_character_ids=(character_id,),
            user_id=None,
            ephemeral=False,
            source_ref=d.SourceRef(source_id=SONG_KNOWLEDGE_SOURCE),
            external_song_id=candidate.song_name,
            revision=content_revision(candidate),
            candidate=d.SongKnowledgeCandidate(
                song_name=candidate.song_name,
                uploader=candidate.uploader or None,
                singers=candidate.singers,
                introduction=candidate.introduction,
                lyrics=candidate.lyrics or None,
                lyric_keywords=candidate.lyric_keywords,
            ),
            fetched_at=now,
        )
