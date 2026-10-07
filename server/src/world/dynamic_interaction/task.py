"""动态互动：选择待处理的动态目标并投递观察事实，由 Agent 决定回复与记忆。

world 只保留选择与业务状态：240s 调度、待回复/待记忆目标的批量上限、`dynamic_store`
的 reply/memory 状态列、来源唯一性防重复。是否回复、回复什么、是否写入记忆全部交给 Agent；
「回复被拒绝」或「决定不回复」经结算端口回写，世界侧不再读取 Agent 的内部返回值。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import src.domain.agent as d
from src.utils.logger import get_logger
from src.world.types.task_result import WorldTaskResult
from src.world.types.world_task import WorldTask
from src.world.world_settlements import (
    FactHandlingOutcome,
    FactPlanOutcome,
    WorldSettlementRouter,
)

if TYPE_CHECKING:
    from src.infrastructure.persistence.database import DatabaseManager
    from src.server_runtime import ServerRuntime
    from src.stage.world_stage import WorldStage

REPLY_ASPECT = "reply"
MEMORY_ASPECT = "memory"
TERMINAL_REPLY_STATUSES = ("replied", "ignored")
TERMINAL_MEMORY_STATUSES = ("written", "ignored")


class _TargetSettlement:
    """一个待处理目标的事实结算订阅者：把处理/执行结果写回该目标的状态列。"""

    def __init__(
        self,
        task: DynamicInteractionTask,
        *,
        stimulus_id: str,
        target_id: str,
        target_kind: d.DynamicTargetKind,
    ) -> None:
        self._task = task
        self._stimulus_id = stimulus_id
        self._target_id = target_id
        self._target_kind = target_kind

    @property
    def aspects(self) -> tuple[str, ...]:
        """该事实同时承担的方面（回复、记忆）。"""
        return self._task._submitted_aspects(self._target_id, self._target_kind)

    def on_fact_handled(self, outcome: FactHandlingOutcome) -> None:
        """处理结算：失败即两个方面都失败；被消费即记忆方面已完成处理。"""
        failed = outcome.error_code is not None or (outcome.request_status is d.HandlingRequestStatus.FAILED)
        if failed:
            self._write("failed", error=str(outcome.error_code or ""))
            return
        self._write_memory("written")
        if outcome.ignored:
            self._write_reply("ignored")

    def on_fact_plan_executed(self, outcome: FactPlanOutcome) -> None:
        """执行结算：只有真正提交了评论效果才算已回复，且按实际提交回写。"""
        committed = next(
            (ref for ref in outcome.effect_refs if ref.kind is d.EffectKind.DYNAMIC_COMMENT),
            None,
        )
        if committed is not None:
            self._write_reply("replied", force=True)
            return
        self._write_reply(
            "failed",
            force=True,
            error="；".join(
                str(item.error_code or item.status) for item in outcome.report.action_results if item.effect_ref is None
            )
            or "计划未提交评论效果",
        )

    def _write_reply(self, status: str, *, error: str | None = None, force: bool = False) -> None:
        if not force and REPLY_ASPECT not in self.aspects:
            return
        self._task.record_outcome(self._target_id, self.aspects, REPLY_ASPECT, status)
        if status in TERMINAL_REPLY_STATUSES:
            error = None
        if self._target_kind is d.DynamicTargetKind.POST:
            self._task.database_manager.dynamic_store.update_dynamic_post_reply_state(
                self._target_id,
                status=status,
                error=error,
            )
        else:
            self._task.database_manager.dynamic_store.update_dynamic_comment_reply_state(
                self._target_id,
                status=status,
                error=error,
            )

    def _write_memory(self, status: str, *, error: str | None = None) -> None:
        if MEMORY_ASPECT not in self.aspects:
            return
        self._task.record_outcome(self._target_id, self.aspects, MEMORY_ASPECT, status)
        if status in TERMINAL_MEMORY_STATUSES:
            error = None
        if self._target_kind is d.DynamicTargetKind.POST:
            self._task.database_manager.dynamic_store.update_dynamic_post_memory_state(
                self._target_id,
                status=status,
                error=error,
            )
        else:
            self._task.database_manager.dynamic_store.update_dynamic_comment_memory_state(
                self._target_id,
                status=status,
                error=error,
            )

    def _write(self, status: str, *, error: str | None = None) -> None:
        """失败同时落在两个方面，避免把未结算的目标留成 pending。"""
        self._write_reply(status, error=error)
        self._write_memory(status, error=error)


class DynamicInteractionTask(WorldTask):
    """按上限选择待处理的动态目标，投递观察事实并接收结算回写。"""

    task_name = "dynamic_interaction"

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        *,
        character_id: str | None = None,
        settlements: WorldSettlementRouter | None = None,
    ) -> None:
        merged_config = dict(config or {})
        merged_config.setdefault(
            "clock_config",
            {"type": "interval", "params": {"interval_seconds": 240, "run_immediately": False}},
        )
        super().__init__(self.task_name, merged_config)
        self.logger = get_logger(__name__)
        self.server_runtime: ServerRuntime | None = None
        self.database_manager: DatabaseManager | None = None
        self.settlements = settlements
        self.character_id = str(character_id or merged_config.get("character_id", "luotianyi"))
        self._outcomes: dict[tuple[str, str], str] = {}
        self._submitted: dict[tuple[str, str], tuple[str, ...]] = {}

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
            raise RuntimeError(f"DynamicInteractionTask dependencies are missing: {', '.join(missing)}")

    async def run_once(self) -> WorldTaskResult:
        """一轮动态互动：先投递待回复目标，再投递待记忆目标，随后汇总结算。"""
        self.ensure_dependencies()
        if self.database_manager is None:
            return WorldTaskResult.skipped_result(
                self.task_name,
                "dynamic interaction dependencies are unavailable",
            )
        self._outcomes.clear()
        self._submitted.clear()
        reply_stats = await self._process_aspect(
            REPLY_ASPECT,
            posts=self.database_manager.dynamic_store.list_pending_dynamic_posts_for_reply(
                limit=int(self.config.get("reply_post_limit", 10)),
            ),
            comments=self.database_manager.dynamic_store.list_pending_dynamic_comments_for_reply(
                limit=int(self.config.get("reply_comment_limit", 20)),
            ),
        )
        memory_stats = await self._process_aspect(
            MEMORY_ASPECT,
            posts=self.database_manager.dynamic_store.list_pending_dynamic_posts_for_memory(
                limit=int(self.config.get("memory_post_limit", 10)),
            ),
            comments=self.database_manager.dynamic_store.list_pending_dynamic_comments_for_memory(
                limit=int(self.config.get("memory_comment_limit", 20)),
            ),
        )
        return WorldTaskResult.success(
            self.task_name,
            "dynamic interaction pass completed",
            **reply_stats,
            **memory_stats,
        )

    async def _process_aspect(
        self,
        aspect: str,
        *,
        posts: list[dict[str, Any]],
        comments: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """投递某一方面的待处理目标；同一目标在一轮内最多投递一次。"""
        submitted = 0
        rejected = 0
        skipped = 0
        for target_kind, items in (
            (d.DynamicTargetKind.POST, posts),
            (d.DynamicTargetKind.COMMENT, comments),
        ):
            for item in items:
                target_id = str(item.get("id") or "")
                key = (target_id, target_kind.value)
                aspects = self._submitted_aspects(target_id, target_kind)
                if aspects:
                    # 同一目标已在上一方面投递过：本轮共享同一条事实，只补记方面
                    self._submitted[key] = aspects + (aspect,)
                    continue
                fact = self._build_observation(item, target_kind)
                if fact is None:
                    skipped += 1
                    continue
                self._submitted[key] = aspects + (aspect,)
                if await self._submit(fact, target_id, target_kind):
                    submitted += 1
                else:
                    rejected += 1
        covered = sum(1 for aspects in self._submitted.values() if aspect in aspects)
        counts = {
            "processed": covered,
            "replied": 0,
            "ignored": 0,
            "written": 0,
            "failed": 0,
            "pending": 0,
        }
        for (target_id, _target_kind), aspects in self._submitted.items():
            if aspect not in aspects:
                continue
            status = self._outcomes.get((target_id, aspect))
            if status is None:
                counts["pending"] += 1
            elif status in counts:
                counts[status] += 1
        return {
            f"{aspect}_processed": counts["processed"],
            f"{aspect}_replied": counts["replied"],
            f"{aspect}_ignored": counts["ignored"],
            f"{aspect}_written": counts["written"],
            f"{aspect}_failed": counts["failed"],
            f"{aspect}_pending": counts["pending"],
            f"{aspect}_rejected": rejected,
            f"{aspect}_skipped": skipped,
        }

    def _submitted_aspects(self, target_id: str, target_kind: d.DynamicTargetKind) -> tuple[str, ...]:
        """本轮已为该目标投递的方面；不含则返回空元组。"""
        key = (target_id, target_kind.value)
        return self._submitted.get(key, ())

    async def _submit(
        self,
        fact: d.DynamicObserved,
        target_id: str,
        target_kind: d.DynamicTargetKind,
    ) -> bool:
        """登记结算订阅并投递事实；被拒绝时撤销登记且不重试。"""
        stage = await self._world_stage()
        if stage is None:
            self.logger.warning("WorldStage 不可用，动态事实未投递：%s", target_id)
            return False
        subscriber = _TargetSettlement(
            self,
            stimulus_id=fact.stimulus_id,
            target_id=target_id,
            target_kind=target_kind,
        )
        if self.settlements is not None:
            self.settlements.register(fact.stimulus_id, subscriber)
        if await stage.fact_sink.submit(fact):
            return True
        if self.settlements is not None:
            self.settlements.discard(fact.stimulus_id)
        self._submitted.pop((target_id, target_kind.value), None)
        self.logger.warning("动态事实被 WorldStage 拒绝：%s", target_id)
        return False

    async def _world_stage(self) -> WorldStage | None:
        """取得本角色长期 WorldStage；运行时不支持时返回 None。"""
        server_runtime = self.server_runtime
        agent_runtime = getattr(server_runtime, "agent_runtime", None)
        character_id = str(getattr(agent_runtime, "default_character_id", None) or self.character_id)
        get_world_stage = getattr(server_runtime, "get_world_stage", None)
        if not callable(get_world_stage):
            return None
        return await get_world_stage(character_id)

    def record_outcome(
        self,
        target_id: str,
        aspects: tuple[str, ...],
        aspect: str,
        status: str,
    ) -> None:
        """记录某目标某方面的结算结果，供本轮统计使用。"""
        if aspect in aspects:
            self._outcomes[(target_id, aspect)] = status

    def _build_observation(
        self,
        item: dict[str, Any],
        target_kind: d.DynamicTargetKind,
    ) -> d.DynamicObserved | None:
        """把待处理条目规范化为一次动态观察；素材不足时返回 None。"""
        messages = self._build_messages(item, target_kind)
        if not messages:
            self.logger.warning(
                "动态目标缺少可投递正文，本轮跳过：%s",
                item.get("id"),
            )
            return None
        now = datetime.now(timezone.utc)
        return d.DynamicObserved(
            stimulus_id=str(uuid4()),
            schema_version=1,
            occurred_at=now,
            source=d.StimulusSource.WORLD,
            target_character_ids=(self.character_id,),
            user_id=None,
            ephemeral=False,
            dynamic_id=str(item.get("dynamic_id") or item.get("id") or ""),
            target_message_id=str(item.get("id") or ""),
            target_kind=target_kind,
            messages=tuple(messages),
            revision=len(messages),
        )

    def _build_messages(
        self,
        item: dict[str, Any],
        target_kind: d.DynamicTargetKind,
    ) -> list[d.DynamicMessage]:
        """按「原帖在前、评论随后」的顺序构造结构化线程。"""
        dynamic = item.get("dynamic") if target_kind is d.DynamicTargetKind.COMMENT else item
        post = dynamic if isinstance(dynamic, dict) else {}
        dynamic_id = str(post.get("id") or item.get("id") or "")
        post_text = str(post.get("content") or "").strip()
        if not dynamic_id or not post_text:
            return []
        messages = [
            d.DynamicMessage(
                message_id=dynamic_id,
                parent_message_id=None,
                author_ref=d.ActorRef(
                    actor_id=str(post.get("author_id") or ""),
                    display_name=str(post.get("author_name") or "") or None,
                ),
                text=post_text,
                media_refs=(),
            )
        ]
        for comment in item.get("thread_comments") or []:
            if not isinstance(comment, dict):
                continue
            comment_id = str(comment.get("id") or "")
            text = str(comment.get("content") or "").strip()
            if not comment_id or not text:
                continue
            parent_id = str(comment.get("parent_comment_id") or dynamic_id)
            known = {message.message_id for message in messages}
            messages.append(
                d.DynamicMessage(
                    message_id=comment_id,
                    parent_message_id=parent_id if parent_id in known else dynamic_id,
                    author_ref=d.ActorRef(
                        actor_id=str(comment.get("author_id") or ""),
                        display_name=str(comment.get("author_name") or "") or None,
                    ),
                    text=text,
                    media_refs=(),
                )
            )
        if target_kind is d.DynamicTargetKind.COMMENT:
            target_id = str(item.get("id") or "")
            if target_id not in {message.message_id for message in messages}:
                return []
        return messages
