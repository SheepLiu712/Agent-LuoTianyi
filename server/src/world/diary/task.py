"""
日记生成世界任务：每天检查高活跃用户，为互动量达标的用户生成日记。

日记以 Agent 动态（可见性=private）形式通过 DynamicCapability 发布，
用户可在现有动态界面中查看。

调度：每天 UTC 16:00（北京时间 0:00）运行一次。
活跃度阈值：当日总对话数 >= 50 条（约 25 轮问答）。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, TYPE_CHECKING

from sqlalchemy import func
from src.utils.logger import get_logger
from src.world.types.task_result import WorldTaskResult
from src.world.types.world_task import WorldTask

if TYPE_CHECKING:
    from src.system.database import DatabaseManager
    from src.system.system_runtime import SystemRuntime
    from src.agent_runtime.character_runtime import CharacterRuntime


class DiaryTask(WorldTask):
    task_name = "diary"

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        merged_config = dict(config or {})
        merged_config.setdefault(
            "clock_config",
            {
                "type": "cron",
                "params": {
                    "hour": 16,       # 北京时间 0:00 (UTC+8)
                    "minute": 0,
                    "run_immediately": False,
                },
            },
        )
        super().__init__(self.task_name, merged_config)
        self.logger = get_logger(__name__)
        self.system_runtime: "SystemRuntime" | None = None
        self.database_manager: "DatabaseManager" | None = None
        self.character_runtime: "CharacterRuntime" | None = None
        self.character_id = str(self.config.get("character_id", "luotianyi"))
        self.character_name = str(self.config.get("character_name", "洛天依"))

        # 高活跃用户阈值：当日总对话数 >= 50 条（约 25 轮问答）
        # 对日活用户来说，50 条以下是比较随意的聊天，50 条以上才算高活跃
        self.min_daily_conversations = int(self.config.get("min_daily_conversations", 50))
        self.max_users_per_run = int(self.config.get("max_users_per_run", 20))

    def initialize(self, system_runtime: "SystemRuntime") -> None:
        self.system_runtime = system_runtime
        self.database_manager = getattr(system_runtime, "database_manager", None)
        agent_runtime = getattr(system_runtime, "agent_runtime", None)
        try:
            runtime = agent_runtime.get_character_runtime(self.character_id) if agent_runtime is not None else None
            if runtime is not None:
                self.character_runtime = runtime
                self.character_name = (
                    getattr(getattr(runtime, "profile", None), "display_name", self.character_name)
                    or self.character_name
                )
        except Exception:
            pass

    def ensure_dependencies(self) -> None:
        super().ensure_dependencies()
        required = {
            "system_runtime": self.system_runtime,
            "database_manager": self.database_manager,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise RuntimeError(f"DiaryTask dependencies are missing: {', '.join(missing)}")

    async def run_once(self) -> WorldTaskResult:
        self.ensure_dependencies()

        diary_cap = self._get_diary_capability()
        if diary_cap is None:
            return WorldTaskResult.skipped_result(self.task_name, "diary capability is unavailable")

        if not diary_cap.ensure_llm():
            return WorldTaskResult.skipped_result(self.task_name, "diary LLM module is unavailable")

        # 获取角色人设和表达风格
        character_persona = ""
        speaking_style = ""
        if self.character_runtime is not None:
            try:
                ctx = self.character_runtime.dynamic_context()
                character_persona = getattr(ctx, "character_persona", "") or ""
                speaking_style = getattr(ctx, "speaking_style", "") or ""
            except Exception as exc:
                self.logger.warning(f"Failed to get character context: {exc}")

        today_str = date.today().strftime("%Y-%m-%d")
        active_users = self._find_active_users(today_str)

        if not active_users:
            self.logger.info("No active users found for diary generation")
            return WorldTaskResult.success(
                self.task_name,
                "no active users found",
                active_users_count=0,
                diaries_created=0,
            )

        created_count = 0
        failed_count = 0

        for user_id in active_users[: self.max_users_per_run]:
            ok, msg, item = await diary_cap.generate_and_post_diary(
                user_id=user_id,
                character_id=self.character_id,
                character_name=self.character_name,
                character_persona=character_persona,
                speaking_style=speaking_style,
                diary_date=today_str,
            )

            if ok:
                created_count += 1
            elif "已有日记" in msg:
                # 已有日记不算失败
                continue
            else:
                failed_count += 1
                self.logger.warning(f"Diary generation failed for user={user_id}: {msg}")

        return WorldTaskResult.success(
            self.task_name,
            f"diary generation completed: {created_count} created, {failed_count} failed",
            active_users_count=len(active_users),
            diaries_created=created_count,
            diaries_failed=failed_count,
        )

    def _find_active_users(self, target_date: str) -> List[str]:
        """
        查找高活跃用户：在目标日期互动量 >= min_daily_conversations 的用户，
        且当天尚未生成日记的用户。
        """
        if self.database_manager is None:
            return []
        db = self.database_manager

        try:
            sql_session = db.get_sql_session()
            if sql_session is None:
                return []

            from src.system.database.sql_database import Conversation, DynamicPost

            try:
                today_start = f"{target_date} 00:00:00"
                today_end = f"{target_date} 23:59:59"

                # 子查询：当天已有日记的用户
                existing_diary = (
                    sql_session.query(DynamicPost.owner_user_id)
                    .filter(DynamicPost.source_type == "diary")
                    .filter(DynamicPost.created_at >= today_start)
                    .filter(DynamicPost.created_at <= today_end)
                    .subquery()
                )

                results = (
                    sql_session.query(
                        Conversation.user_id,
                        func.count(Conversation.id).label("msg_count"),
                    )
                    .filter(Conversation.timestamp >= today_start)
                    .filter(Conversation.timestamp <= today_end)
                    .filter(Conversation.character_id == self.character_id)
                    # 排除已有日记的用户
                    .filter(~Conversation.user_id.in_(sql_session.query(existing_diary.c.owner_user_id)))
                    .group_by(Conversation.user_id)
                    .having(func.count(Conversation.id) >= self.min_daily_conversations)
                    .all()
                )

                active_users = [row.user_id for row in results]

                # 清理空字符串
                active_users = [uid for uid in active_users if uid]
                return active_users

            except Exception as exc:
                self.logger.error(f"Query active users failed: {exc}")
                return []
            finally:
                sql_session.close()

        except Exception as exc:
            self.logger.error(f"Failed to find active users: {exc}")
            return []

    def _get_diary_capability(self):
        if self.system_runtime is None:
            return None
        capability_manager = getattr(self.system_runtime, "capability_manager", None)
        if capability_manager is None:
            return None
        return getattr(capability_manager, "diary", None)