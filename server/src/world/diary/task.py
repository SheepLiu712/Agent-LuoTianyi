"""
日记生成世界任务：每天检查高活跃用户，为有足够互动的用户生成日记。

调度逻辑：
- 每天在指定时间运行一次（默认 UTC 16:00，即北京时间 0:00）
- 遍历所有活跃用户，检查当日互动量
- 互动量达标且尚未有日记的用户，触发日记生成
"""
from __future__ import annotations

import json
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

        # 活跃度阈值：当日互动消息数达到此值才生成日记
        self.min_daily_conversations = int(self.config.get("min_daily_conversations", 10))
        # 最大日记生成用户数（单次运行）
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

        if self.database_manager is None:
            return WorldTaskResult.skipped_result(self.task_name, "database_manager is unavailable")

        diary_capability = self._get_diary_capability()
        if diary_capability is None:
            return WorldTaskResult.skipped_result(self.task_name, "diary capability is unavailable")

        if not diary_capability.ensure_llm():
            return WorldTaskResult.skipped_result(self.task_name, "diary LLM module is unavailable")

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

        self.logger.info(f"Found {len(active_users)} active users for diary generation")
        created_count = 0
        skipped_count = 0
        failed_count = 0

        for user_id in active_users[: self.max_users_per_run]:
            ok, msg, item = await diary_capability.generate_diary(
                user_id=user_id,
                character_id=self.character_id,
                character_name=self.character_name,
                diary_date=today_str,
            )

            if ok:
                created_count += 1
                self.logger.info(f"Diary created for user={user_id}")
            elif "已有日记" in msg:
                skipped_count += 1
            else:
                failed_count += 1
                self.logger.warning(f"Diary generation failed for user={user_id}: {msg}")

        return WorldTaskResult.success(
            self.task_name,
            f"diary generation completed: {created_count} created, {skipped_count} skipped, {failed_count} failed",
            active_users_count=len(active_users),
            diaries_created=created_count,
            diaries_skipped=skipped_count,
            diaries_failed=failed_count,
        )

    def _find_active_users(self, target_date: str) -> List[str]:
        """
        查找活跃用户：在目标日期有足够互动量的用户。
        这里使用简单策略——检查今日有聊天记录的用户。
        """
        if self.database_manager is None:
            return []

        db = self.database_manager
        active_users: List[str] = []

        try:
            # 从会话记录中查找活跃用户
            # 获取所有有聊天记录的用户
            sql_session = db.get_sql_session()
            if sql_session is None:
                return []

            from src.system.database.sql_database import Conversation, User

            try:
                # 查找今天有聊天记录的用户
                today_start = f"{target_date} 00:00:00"
                today_end = f"{target_date} 23:59:59"

                results = (
                    sql_session.query(
                        Conversation.user_id,
                        Conversation.character_id,
                        func.count(Conversation.id).label("msg_count"),
                    )
                    .filter(Conversation.timestamp >= today_start)
                    .filter(Conversation.timestamp <= today_end)
                    .filter(Conversation.character_id == self.character_id)
                    .group_by(Conversation.user_id, Conversation.character_id)
                    .having(func.count(Conversation.id) >= self.min_daily_conversations)
                    .all()
                )

                for row in results:
                    user_id = row[0]
                    # 检查是否已有日记
                    if db.diary_store and not db.diary_store.has_diary_for_date(
                        user_id, target_date, character_id=self.character_id
                    ):
                        active_users.append(user_id)

            except Exception as exc:
                self.logger.error(f"Query active users failed: {exc}")
            finally:
                sql_session.close()

        except Exception as exc:
            self.logger.error(f"Failed to find active users: {exc}")

        return active_users

    def _get_diary_capability(self):
        """获取日记能力实例。"""
        if self.system_runtime is None:
            return None
        capability_manager = getattr(self.system_runtime, "capability_manager", None)
        if capability_manager is None:
            return None
        return getattr(capability_manager, "diary", None)