"""
日记生成世界任务：每天检查高活跃用户，为互动量达标的用户生成日记。

## 调度策略

通过 WorldClock 的 daily 调度，每天 UTC+8 0:00 运行一次。

## 活跃度判断

用户当日总对话数 >= 50 条才算高活跃（约 25 轮问答）。
50 条以下的用户对话较为随意，生成的日记素材不充分。

## 日记发布方式

日记以 Agent 动态（可见性=private）形式通过 DynamicCapability 发布，
用户可在现有动态界面中查看，无需独立存储。

## 数据流

  DiaryTask.run_once()
    → _find_active_users()          # SQL 查询当日高活跃且无日记的用户
    → DiaryCapability.generate_and_post_diary()  # 逐个生成并发布
      → _collect_materials()        # 收集聊天记录 + 动态
      → LLM 生成                     # 调用日记专用 LLM 模块
      → publish_agent_dynamic()     # 发布为私有动态
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, TYPE_CHECKING

from sqlalchemy import and_, func, or_
from src.utils.logger import get_logger
from src.world.types.task_result import WorldTaskResult
from src.world.types.world_task import WorldTask

if TYPE_CHECKING:
    from src.system.database import DatabaseManager
    from src.system.system_runtime import SystemRuntime
    from src.agent_runtime.character_runtime import CharacterRuntime


class DiaryTask(WorldTask):
    """
    日记生成世界任务。

    继承自 WorldTask，通过 WorldClock 的 daily 机制每天触发一次。
    task_name = "diary" 用于配置系统中的任务开关和参数覆盖。
    """

    base_task_name = "diary"

    def __init__(self, config: Dict[str, Any] | None = None, character_id: str = "luotianyi") -> None:
        """
        初始化日记任务。

        Args:
            config: 配置项，支持以下字段：
                - character_id: 角色 ID（默认 luotianyi）
                - character_name: 角色名称（默认 洛天依）
                - min_daily_conversations: 日对话数阈值（默认 50）
                - max_users_per_run: 单次最多处理的用户数（默认 20）
                - clock_config: 世界时钟调度配置（默认每天 UTC+8 0:00）
                - enabled: 是否启用此任务（由世界任务系统读取）
            character_id: 角色 ID，用于多角色场景
        """
        self.character_id = character_id
        merged_config = dict(config or {})

        # 设置默认调度时间：每天 UTC+8 0:00 运行
        # 系统已使用 UTC+8 时区，hour=0 即为每天午夜
        merged_config.setdefault(
            "clock_config",
            {
                "type": "daily",
                "params": {
                    "hour": 0,
                    "minute": 0,
                },
            },
        )
        super().__init__(f"{self.base_task_name}:{character_id}", merged_config)
        self.logger = get_logger(__name__)

        # ── 外部依赖（由 initialize 注入） ──
        self.system_runtime: "SystemRuntime" | None = None
        self.database_manager: "DatabaseManager" | None = None
        self.character_runtime: "CharacterRuntime" | None = None

        # ── 角色标识 ──
        # character_id 由构造函数参数传入（多角色场景）或从 config 读取
        if not self.character_id:
            self.character_id = str(self.config.get("character_id", "luotianyi"))
        self.character_name = str(self.config.get("character_name", "洛天依"))

        # ── 阈值参数 ──
        # 高活跃用户阈值：当日总对话数 >= 50 条（约 25 轮问答）
        # 对日活用户来说，50 条以下是比较随意的聊天，50 条以上才算真正的高活跃
        self.min_daily_conversations = int(self.config.get("min_daily_conversations", 50))
        # 单次运行最多处理 20 个用户，防止任务执行时间过长
        self.max_users_per_run = int(self.config.get("max_users_per_run", 20))

    # ────────────────────── 生命周期 ──────────────────────

    def initialize(self, system_runtime: "SystemRuntime") -> None:
        """
        由系统运行时在启动时调用，注入外部依赖。

        这里获取：
          - database_manager: 用于查询活跃用户
          - character_runtime: 用于获取角色人设和表达风格
          - character_name: 从角色配置中读取显示名称
        """
        self.system_runtime = system_runtime
        # database_manager 是必要依赖，直接访问以便尽早暴露配置错误
        self.database_manager = system_runtime.database_manager
        agent_runtime = getattr(system_runtime, "agent_runtime", None)
        try:
            runtime = agent_runtime.get_character_runtime(self.character_id) if agent_runtime is not None else None
            if runtime is not None:
                self.character_runtime = runtime
                # 从角色配置中获取更准确的显示名称（如配置了自定义名称）
                self.character_name = (
                    getattr(getattr(runtime, "profile", None), "display_name", self.character_name)
                    or self.character_name
                )
        except Exception as exc:
            # 角色运行时获取失败不影响任务启动，后续 run_once 中
            # 会使用默认的人设和风格
            self.logger.warning(f"Failed to get character runtime for diary: {exc}")

    def ensure_dependencies(self) -> None:
        """运行前检查必要依赖是否已就绪。"""
        super().ensure_dependencies()
        required = {
            "system_runtime": self.system_runtime,
            "database_manager": self.database_manager,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise RuntimeError(f"DiaryTask dependencies are missing: {', '.join(missing)}")

    # ────────────────────── 核心逻辑 ──────────────────────

    async def run_once(self) -> WorldTaskResult:
        """
        执行一次日记生成任务。

        执行步骤：
          1. 检查依赖和 LLM 可用性
          2. 从 CharacterRuntime 获取角色人设和表达风格
          3. 查询当日高活跃用户（互动量 >= 阈值且尚未有日记）
          4. 逐个调用 DiaryCapability.generate_and_post_diary()
          5. 统计成功/失败数量并返回结果

        Returns:
            WorldTaskResult: 包含执行结果统计的任务结果
        """
        self.ensure_dependencies()

        # 获取日记能力实例
        diary_cap = self._get_diary_capability()
        if diary_cap is None:
            return WorldTaskResult.skipped_result(self.task_name, "diary capability is unavailable")

        # 检查 LLM 模块是否已注册（每天仅运行一次，缺失时明确记录原因）
        if not diary_cap.ensure_dependency():
            self.logger.warning("Diary LLM module is not registered; diary task skipped for today")
            return WorldTaskResult.skipped_result(self.task_name, "diary LLM module is unavailable")

        # 角色运行时缺失时降级使用默认人设（不阻断任务）
        if self.character_runtime is None:
            self.logger.warning(
                "Character runtime for %s is unavailable; diary will use default persona", self.character_id
            )

        # ── 获取角色人设和表达风格 ──
        # 这些信息会被注入到日记 prompt 中，让生成的日记更符合角色设定
        character_persona = ""
        speaking_style = ""
        if self.character_runtime is not None:
            try:
                ctx = self.character_runtime.dynamic_context()
                character_persona = getattr(ctx, "character_persona", "") or ""
                speaking_style = getattr(ctx, "speaking_style", "") or ""
            except Exception as exc:
                self.logger.warning(f"Failed to get character context: {exc}")

        # ── 查询高活跃用户 ──
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

        # ── 逐个生成日记 ──
        # 若活跃用户超出单次上限，随机取 max_users_per_run 个
        # 避免每次只处理 SQL 前 N 条，保证所有用户都有机会被写到日记
        created_count = 0
        failed_count = 0
        selected_users = (
            random.sample(active_users, self.max_users_per_run)
            if len(active_users) > self.max_users_per_run
            else active_users
        )

        for user_id in selected_users:
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

    # ────────────────────── 活跃用户查询 ──────────────────────

    def _find_active_users(self, target_date: str) -> List[str]:
        """
        查找高活跃用户：在目标日期互动量 >= min_daily_conversations 的用户，
        且当天尚未生成日记的用户。

        SQL 查询逻辑：
          1. 主查询：从 Conversation 表中按 user_id 分组统计当日对话数
          2. 过滤条件：对话时间在目标日期范围内，角色 ID 匹配
          3. 排除子查询：已有日记的用户（DynamicPost.source_type == "diary"）
          4. HAVING：对话数 >= 阈值

        使用子查询排除已有日记的用户，可以避免无效的 LLM 调用。

        Args:
            target_date: 目标日期（YYYY-MM-DD）

        Returns:
            活跃用户 ID 列表
        """
        if self.database_manager is None:
            return []
        db = self.database_manager

        try:
            sql_session = db.get_sql_session()
            if sql_session is None:
                return []

            # 延迟导入避免循环引用
            from src.system.database.sql_database import Conversation, DynamicPost

            try:
                # 将目标日期转为 datetime 范围 [day_start, day_end)
                # 用 datetime 对象做边界比较，避免字符串比较在
                # 微秒/时区格式下的边界误差
                day_start = datetime.strptime(target_date, "%Y-%m-%d")
                day_end = day_start + timedelta(days=1)

                # 子查询：当天已有日记的用户
                # 日记动态的 source_type == "diary"，可见性为 private
                existing_diary = (
                    sql_session.query(DynamicPost.owner_user_id)
                    .filter(DynamicPost.source_type == "diary")
                    .filter(DynamicPost.author_type == "agent")
                    .filter(DynamicPost.author_id == self.character_id)
                    .filter(DynamicPost.status == "published")
                    .filter(
                        or_(
                            DynamicPost.source_id.endswith(f":{target_date}"),
                            and_(
                                DynamicPost.source_id.is_(None),
                                DynamicPost.created_at >= day_start,
                                DynamicPost.created_at < day_end,
                            ),
                        )
                    )
                    .subquery()
                )

                # 主查询：活跃用户（排除已有日记的）
                results = (
                    sql_session.query(
                        Conversation.user_id,
                        func.count(Conversation.uuid).label("msg_count"),
                    )
                    .filter(Conversation.timestamp >= day_start)
                    .filter(Conversation.timestamp < day_end)
                    .filter(Conversation.character_id == self.character_id)
                    # 排除已有日记的用户——避免无效 LLM 调用
                    .filter(~Conversation.user_id.in_(sql_session.query(existing_diary.c.owner_user_id)))
                    .group_by(Conversation.user_id)
                    .having(func.count(Conversation.uuid) >= self.min_daily_conversations)
                    .all()
                )

                # 使用命名属性访问（row.user_id），比索引访问更健壮
                active_users = [row.user_id for row in results]

                # 过滤掉可能的空字符串（数据库异常数据防卫）
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

    # ────────────────────── 能力获取 ──────────────────────

    def _get_diary_capability(self) -> Any | None:
        """
        从系统运行时中获取 DiaryCapability 实例。

        查找路径：
          system_runtime → capability_manager → diary

        Returns:
            DiaryCapability 实例，如果系统未就绪则返回 None
        """
        if self.system_runtime is None:
            return None
        capability_manager = getattr(self.system_runtime, "capability_manager", None)
        if capability_manager is None:
            return None
        return getattr(capability_manager, "diary", None)
