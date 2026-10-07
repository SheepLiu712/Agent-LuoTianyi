"""筛选当日高活跃用户并投递日记规划事实。"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_

import src.domain.agent as d
from src.utils.logger import get_logger
from src.world.types.task_result import WorldTaskResult
from src.world.types.world_task import WorldTask
from src.world.world_settlements import FactHandlingOutcome, FactPlanOutcome

if TYPE_CHECKING:
    from src.stage.world_stage import WorldStage
    from src.infrastructure.persistence.database import DatabaseManager
    from src.server_runtime import ServerRuntime
    from src.world.world_settlements import WorldSettlementRouter


class _DiarySettlement:
    """把一个用户的日记事实结算为 created 或 failed。"""

    def __init__(self, task: DiaryTask, owner_user_id: str) -> None:
        self._task = task
        self._owner_user_id = owner_user_id

    def on_fact_handled(self, outcome: FactHandlingOutcome) -> None:
        if outcome.request_status is d.HandlingRequestStatus.FAILED or outcome.error_code is not None:
            self._task.record_outcome(self._owner_user_id, "failed")
        elif outcome.ignored:
            self._task.record_outcome(self._owner_user_id, "failed")

    def on_fact_plan_executed(self, outcome: FactPlanOutcome) -> None:
        created = any(ref.kind is d.EffectKind.DYNAMIC_POST for ref in outcome.effect_refs)
        self._task.record_outcome(self._owner_user_id, "created" if created else "failed")


class DiaryTask(WorldTask):
    """在午夜选择符合条件且当天尚无日记的用户并投递事实。"""

    base_task_name = "diary"

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        character_id: str = "luotianyi",
        settlements: WorldSettlementRouter | None = None,
    ) -> None:
        merged_config = dict(config or {})
        merged_config.setdefault(
            "clock_config", {"type": "daily", "params": {"hour": 0, "minute": 0}},
        )
        super().__init__(f"{self.base_task_name}:{character_id}", merged_config)
        self.logger = get_logger(__name__)
        self.character_id = character_id or str(self.config.get("character_id", "luotianyi"))
        self.min_daily_conversations = int(self.config.get("min_daily_conversations", 50))
        self.max_users_per_run = int(self.config.get("max_users_per_run", 20))
        self.timezone = ZoneInfo(str(self.config.get("timezone", "Asia/Shanghai")))
        self.settlements = settlements
        self.server_runtime: ServerRuntime | None = None
        self.database_manager: DatabaseManager | None = None
        self._outcomes: dict[str, str] = {}

    def initialize(self, server_runtime: ServerRuntime) -> None:
        self.server_runtime = server_runtime
        self.database_manager = getattr(server_runtime, "database_manager", None)

    def ensure_dependencies(self) -> None:
        super().ensure_dependencies()
        required = {
            "server_runtime": self.server_runtime,
            "database_manager": self.database_manager,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise RuntimeError(f"DiaryTask dependencies are missing: {', '.join(missing)}")

    async def run_once(self) -> WorldTaskResult:
        """投递本地当天的日记规划事实，并汇总当前已收到的结算。"""
        self.ensure_dependencies()
        now = datetime.now(self.timezone)
        local_date = now.date()
        active_users = self._find_active_users(local_date.isoformat())
        selected_users = (
            random.sample(active_users, self.max_users_per_run)
            if len(active_users) > self.max_users_per_run
            else active_users
        )
        self._outcomes.clear()
        rejected = 0
        trigger_id = f"diary:{self.character_id}:{local_date.isoformat()}"
        for owner_user_id in selected_users:
            fact = d.DiaryPlanningDue(
                stimulus_id=str(uuid4()),
                schema_version=1,
                occurred_at=now,
                source=d.StimulusSource.WORLD,
                target_character_ids=(self.character_id,),
                user_id=None,
                ephemeral=False,
                local_date=local_date,
                timezone=self.timezone,
                trigger_id=trigger_id,
                owner_user_id=owner_user_id,
            )
            if not await self._submit(fact):
                rejected += 1
        counts = {"created": 0, "failed": 0, "pending": 0}
        for owner_user_id in selected_users:
            status = self._outcomes.get(owner_user_id, "pending")
            counts[status] += 1
        return WorldTaskResult.success(
            self.task_name,
            "diary planning pass completed",
            active_users_count=len(active_users),
            selected_users_count=len(selected_users),
            diaries_created=counts["created"],
            diaries_failed=counts["failed"],
            diaries_pending=counts["pending"],
            facts_rejected=rejected,
        )

    async def _submit(self, fact: d.DiaryPlanningDue) -> bool:
        stage = await self._world_stage()
        if stage is None:
            self.logger.warning("WorldStage 不可用，日记事实未投递：%s", fact.owner_user_id)
            return False
        if self.settlements is not None:
            self.settlements.register(
                fact.stimulus_id, _DiarySettlement(self, fact.owner_user_id),
            )
        if await stage.fact_sink.submit(fact):
            return True
        if self.settlements is not None:
            self.settlements.discard(fact.stimulus_id)
        self.logger.warning("日记事实被 WorldStage 拒绝：%s", fact.owner_user_id)
        return False

    async def _world_stage(self) -> WorldStage | None:
        get_world_stage = getattr(self.server_runtime, "get_world_stage", None)
        if not callable(get_world_stage):
            return None
        return await get_world_stage(self.character_id)

    def record_outcome(self, owner_user_id: str, status: str) -> None:
        self._outcomes[owner_user_id] = status

    def _find_active_users(self, target_date: str) -> list[str]:
        """查询达到阈值且该角色当天尚未为其发布日记的用户。"""
        if self.database_manager is None:
            return []
        sql_session = self.database_manager.get_sql_session()
        if sql_session is None:
            return []
        from src.infrastructure.persistence.database.sql_database import Conversation, DynamicPost

        try:
            day_start = datetime.strptime(target_date, "%Y-%m-%d")
            day_end = day_start + timedelta(days=1)
            existing_diary = (
                sql_session.query(DynamicPost.owner_user_id)
                .filter(DynamicPost.source_type == "diary")
                .filter(DynamicPost.author_type == "agent")
                .filter(DynamicPost.author_id == self.character_id)
                .filter(DynamicPost.status == "published")
                .filter(or_(
                    DynamicPost.source_id.endswith(f":{target_date}"),
                    and_(
                        DynamicPost.source_id.is_(None),
                        DynamicPost.created_at >= day_start,
                        DynamicPost.created_at < day_end,
                    ),
                ))
                .subquery()
            )
            results = (
                sql_session.query(Conversation.user_id)
                .filter(Conversation.timestamp >= day_start)
                .filter(Conversation.timestamp < day_end)
                .filter(Conversation.character_id == self.character_id)
                .filter(~Conversation.user_id.in_(
                    sql_session.query(existing_diary.c.owner_user_id),
                ))
                .group_by(Conversation.user_id)
                .having(func.count(Conversation.uuid) >= self.min_daily_conversations)
                .all()
            )
            return [row.user_id for row in results if row.user_id]
        except Exception as exc:  # noqa: BLE001 - database query boundary returns an empty selection
            self.logger.error("查询日记活跃用户失败：%s", exc)
            return []
        finally:
            sql_session.close()
