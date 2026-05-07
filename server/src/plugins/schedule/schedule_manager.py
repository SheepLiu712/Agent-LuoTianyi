"""
调度管理器：统一调度抓取、解析、存储、提醒派发、上下文提供。
运行在独立线程中，内部持有 asyncio event loop 以调用异步 LLM 解析器。
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.utils.logger import get_logger
from .event_models import EventStatus, EventType, ScheduleEvent
from .event_store import EventStore
from .official_feed_fetcher import OfficialFeedFetcher
from .event_parser import EventParser

logger = get_logger(__name__)


class ScheduleManager:
    """
    日程系统核心调度器。

    线程模型：
    - 运行在独立 daemon 线程中
    - 内部创建 asyncio event loop 以驱动异步 LLM 调用
    - 通过外部注入的 service_hub_ref (callable) 访问 GCSM / ChatStream
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        service_hub_ref: Optional[Any] = None,
    ):
        self.config = config or {}
        self.service_hub_ref = service_hub_ref  # 延迟注入，避免循环引用
        self.logger = get_logger(__name__)

        # 子模块
        self.event_store = EventStore(
            data_file=self.config.get("data_file", "data/schedule/events.json")
        )
        self.fetcher = OfficialFeedFetcher(config=self.config)
        llm_cfg = (self.config.get("llm") or {})
        if not llm_cfg:
            # 复用主配置的 knowledge.llm
            from src.utils.helpers import load_config
            cfg = load_config("config/config.json", default_config={})
            llm_cfg = cfg.get("knowledge", {}).get("llm", {})
        self.parser = EventParser(llm_config=llm_cfg)

        # 运行时状态
        self._stop_event = asyncio.Event()
        self._thread: Optional[Any] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._task: Optional[asyncio.Task] = None

        # 配置项
        self.fetch_interval = self.config.get("fetch_interval_hours", 6) * 3600
        self.check_interval = self.config.get("check_interval_seconds", 60)
        reminder_cfg = self.config.get("reminder", {})
        self.advance_days_concert = reminder_cfg.get("advance_days_concert", [3, 1, 0])
        self.advance_days_general = reminder_cfg.get("advance_days_general", [0])
        self.context_lookahead_days = self.config.get("context", {}).get("lookahead_days", 7)
        self.context_max_events = self.config.get("context", {}).get("max_context_events", 5)
        self.mention_cooldown_hours = self.config.get("context", {}).get("mention_cooldown_hours", 6)
        silence_cfg = self.config.get("silence", {})
        self.silence_pre_minutes = silence_cfg.get("concert_pre_start_minutes", 30)
        self.silence_post_minutes = silence_cfg.get("concert_post_end_minutes", 60)

    # ── 生命周期 ─────────────────────────────────────────────

    def start(self) -> None:
        """启动调度线程。"""
        if self._thread and self._thread.is_alive():
            self.logger.warning("ScheduleManager already running")
            return
        self._stop_event.clear()
        self._thread = __import__("threading").Thread(
            target=self._run_loop, name="schedule-manager", daemon=True
        )
        self._thread.start()
        self.logger.info("ScheduleManager started")

    def stop(self) -> None:
        """停止调度线程。"""
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._stop_event.set)
        if self._thread:
            self._thread.join(timeout=10)
        self.logger.info("ScheduleManager stopped")

    def set_service_hub_ref(self, ref: Any) -> None:
        """注入 service_hub 引用（启动后调用）。"""
        self.service_hub_ref = ref

    # ── 主循环 ─────────────────────────────────────────────

    def _run_loop(self) -> None:
        """线程入口：创建 event loop 并运行。"""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._async_main())
        except Exception as e:
            self.logger.error(f"ScheduleManager loop error: {e}")
        finally:
            self._loop.close()

    async def _async_main(self) -> None:
        """异步主循环。"""
        # 启动时先拉一次
        await self._fetch_and_process()

        last_fetch_time = time.time()

        while not self._stop_event.is_set():
            now = time.time()

            # 定期拉取新动态
            if now - last_fetch_time >= self.fetch_interval:
                await self._fetch_and_process()
                last_fetch_time = now

            # 检查需要发送提醒的事件
            await self._check_and_dispatch_reminders()

            # 自动更新事件状态
            self.event_store.refresh_statuses()

            # 等待
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.check_interval)
                break  # stop event set
            except asyncio.TimeoutError:
                continue

    async def _fetch_and_process(self) -> None:
        """拉取新动态 → LLM 解析 → 存储。"""
        self.logger.info("ScheduleManager: fetching new dynamics...")
        try:
            raw_items = self.fetcher.fetch_all_new()
            if not raw_items:
                self.logger.info("No new dynamics fetched")
                return

            self.logger.info(f"Fetched {len(raw_items)} new dynamics, parsing...")
            events = await self.parser.parse_dynamics(raw_items)

            for event in events:
                self.event_store.add_event(event)

            self.event_store.set_last_fetch_time(datetime.now().isoformat())
            self.logger.info(f"Processed {len(events)} new event(s) from dynamics")
        except Exception as e:
            self.logger.error(f"Error in fetch_and_process: {e}")

    # ── 提醒派发 ─────────────────────────────────────────────

    async def _check_and_dispatch_reminders(self) -> None:
        """检查并派发到期的事件提醒。"""
        if not self.service_hub_ref:
            return

        upcoming = self.event_store.get_upcoming()
        now_date = datetime.now().date()

        for event in upcoming:
            advance_days = (
                self.advance_days_concert
                if event.event_type == EventType.CONCERT
                else self.advance_days_general
            )
            start_date = event.start_datetime.date() if event.start_datetime else None
            if not start_date:
                continue

            days_diff = (start_date - now_date).days

            # 判断今天是否需要发送该提醒
            if days_diff not in advance_days:
                continue

            # 获取在线用户列表
            try:
                gcsm = self.service_hub_ref.gcsm
                online_users = self._get_online_user_ids(gcsm)
            except Exception as e:
                self.logger.warning(f"Failed to get online users: {e}")
                continue

            for user_id in online_users:
                if not event.should_send_reminder(advance_days, user_id):
                    continue
                await self._dispatch_reminder_to_user(event, user_id, days_diff)
                event.mark_reminder_sent(days_diff, user_id)
                self.event_store.update_event(event)

    def _get_online_user_ids(self, gcsm: Any) -> List[str]:
        """从 GCSM 获取在线用户的 user_id 列表。"""
        try:
            return list(gcsm.user_streams.keys())
        except Exception:
            return []

    async def _dispatch_reminder_to_user(
        self, event: ScheduleEvent, user_id: str, days_diff: int
    ) -> None:
        """向单个用户发送活动提醒。"""
        try:
            gcsm = self.service_hub_ref.gcsm
            chat_stream = gcsm.user_streams.get(user_id)
            if not chat_stream:
                return

            # 构造提醒文本
            if days_diff == 0:
                time_desc = "今天"
            elif days_diff == 1:
                time_desc = "明天"
            else:
                time_desc = f"{days_diff} 天后"

            type_names = {
                EventType.CONCERT: "演唱会",
                EventType.COLLABORATION: "联动活动",
                EventType.LIVESTREAM: "直播",
                EventType.RELEASE: "新作品发布",
                EventType.ANNIVERSARY: "纪念活动",
                EventType.GENERAL: "活动",
            }
            type_name = type_names.get(event.event_type, "活动")

            content = f"{time_desc}有{type_name}「{event.title}」"
            if event.location:
                content += f"，地点在{event.location}"
            content += "，记得关注哦~"

            from src.pipeline.topic_planner import ExtractedTopic
            import uuid
            topic = ExtractedTopic(
                topic_id=str(uuid.uuid4()),
                source_messages=[],
                topic_content=content,
                memory_attempts=[],
                fact_constraints=[],
                sing_attempts=[],
                is_forced_from_incomplete=True,
            )

            await chat_stream.topic_replier.add_topic(topic)
            self.logger.info(f"Dispatched reminder for '{event.title}' to user {user_id}")

        except Exception as e:
            self.logger.error(f"Failed to dispatch reminder to {user_id}: {e}")

    # ── 静默判断 ─────────────────────────────────────────────

    def is_silence_period(self) -> bool:
        """当前是否处于演唱会的静默时段内。"""
        now = datetime.now()
        for event in self.event_store.get_all():
            if not event.is_concert():
                continue
            start = event.start_datetime
            if not start:
                continue
            pre = start - timedelta(minutes=self.silence_pre_minutes)
            end = event.end_datetime
            if end:
                post = end + timedelta(minutes=self.silence_post_minutes)
            else:
                post = start + timedelta(hours=4)
            if pre <= now <= post:
                return True
        return False

    def get_silence_event(self) -> Optional[ScheduleEvent]:
        """返回当前正在静默的演唱会事件（如有）。"""
        now = datetime.now()
        for event in self.event_store.get_all():
            if not event.is_concert():
                continue
            start = event.start_datetime
            if not start:
                continue
            pre = start - timedelta(minutes=self.silence_pre_minutes)
            end = event.end_datetime
            if end:
                post = end + timedelta(minutes=self.silence_post_minutes)
            else:
                post = start + timedelta(hours=4)
            if pre <= now <= post:
                return event
        return None

    # ── 上下文提供 ─────────────────────────────────────────────

    def get_active_context(self, user_id: str = "") -> str:
        """
        返回当前应注入对话的近期活动摘要文本。
        如果提供了 user_id，会进行频率控制。
        """
        events = self.event_store.get_active_events(lookahead_days=self.context_lookahead_days)
        if not events:
            return ""

        lines: List[str] = ["[活动信息参考]"]
        mentioned = 0
        now = datetime.now()

        for event in events[: self.context_max_events]:
            # 频率控制：如果对该用户最近已提及过，跳过
            if user_id:
                key = f"user_{user_id}"
                sent_days = event.reminder_details.get(key, [])
                # 如果今天已经提醒过，不重复注入上下文
                today_str = now.strftime("%Y-%m-%d")
                if today_str in [str(d) for d in sent_days]:
                    continue

            start_str = event.start_time[:10] if event.start_time else "未知日期"
            type_names_cn = {
                EventType.CONCERT: "演唱会",
                EventType.COLLABORATION: "联动",
                EventType.LIVESTREAM: "直播",
                EventType.RELEASE: "发布",
                EventType.ANNIVERSARY: "纪念日",
                EventType.GENERAL: "活动",
            }
            type_cn = type_names_cn.get(event.event_type, "活动")
            line = f"- {start_str} {type_cn}：「{event.title}」"
            if event.location:
                line += f"（{event.location}）"
            if event.description:
                line += f" - {event.description[:50]}"
            lines.append(line)
            mentioned += 1

        if mentioned == 0:
            return ""
        return "\n".join(lines)

    # ── 手动触发接口（供外部调用）─────────────────────────────

    async def manual_fetch(self) -> Dict[str, Any]:
        """手动触发一次拉取（供 API/调试使用）。"""
        await self._fetch_and_process()
        return {"status": "ok", "events": len(self.event_store.get_all())}

    def get_events(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """查询事件列表。"""
        if status:
            try:
                events = self.event_store.get_by_status(EventStatus(status))
            except ValueError:
                events = self.event_store.get_all()
        else:
            events = self.event_store.get_all()
        return [e.to_dict() for e in events]

    def force_refresh_statuses(self) -> int:
        """强制刷新所有事件状态。"""
        return self.event_store.refresh_statuses()
