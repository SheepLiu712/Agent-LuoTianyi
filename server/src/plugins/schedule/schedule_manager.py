"""
调度管理器：统一调度抓取、解析、存储、提醒派发。
运行在独立线程中，内部持有 asyncio event loop 以驱动异步 LLM 调用。
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from src.utils.logger import get_logger
from src.plugins.schedule.event_models import UnifiedEventType
from src.plugins.schedule.event_store import EventStore
from src.plugins.schedule.official_feed_fetcher import OfficialFeedFetcher
from src.plugins.schedule.event_parser import EventParser
from src.plugins.schedule.reminder_dispatcher import ReminderDispatcher
from src.plugins.schedule.activity_context_provider import ActivityContextProvider

if TYPE_CHECKING:
    from src.system.chat_session.global_chat_stream_manager import GlobalChatStreamManager
    from sqlalchemy.orm import Session

logger = get_logger(__name__)


class ScheduleManager:
    """
    日程系统核心调度器。

    线程模型：
    - 运行在独立 daemon 线程中
    - 内部创建 asyncio event loop 以驱动异步 LLM 调用
    - 通过外部注入的 GCSM 访问 ChatStream
    """

    def __init__(
        self,
        sql_session_factory: Callable[[], Session],
        config: Optional[Dict[str, Any]] = None,
    ):
        self.config = config or {}
        self.logger = get_logger(__name__)

        # 子模块

        self.fetcher = OfficialFeedFetcher(config=self.config)
        llm_cfg = self.config.get("llm") or {}
        vlm_cfg = self.config.get("vlm") or {}
        self.parser = EventParser(llm_config=llm_cfg, vlm_config=vlm_cfg)
        self.event_store = EventStore(
            sql_session_factory=sql_session_factory,
            llm_client=self.parser.llm_client,
        )

        # 上下文提供者
        self.context_provider = ActivityContextProvider(
            event_store=self.event_store,
            mention_cooldown_hours=self.config.get("context", {}).get("mention_cooldown_hours", 6),
            lookahead_days=self.config.get("context", {}).get("lookahead_days", 7),
            max_context_events=self.config.get("context", {}).get("max_context_events", 5),
        )

        # 运行时状态
        self._stop_event = asyncio.Event()
        self._thread: Optional[Any] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # 配置项
        self.fetch_interval = self.config.get("fetch_interval_hours", 6) * 3600 # 6h
        self.check_interval = self.config.get("check_interval_seconds", 60) * 10 # 10min

        # 静默配置
        silence_cfg = self.config.get("silence", {})
        self.silence_pre_minutes = silence_cfg.get("concert_pre_start_minutes", 60)
        self.silence_post_minutes = silence_cfg.get("concert_post_end_minutes", 30)

        # 提醒派发器
        self.reminder_dispatcher = ReminderDispatcher(
            event_store=self.event_store,
            context_provider=self.context_provider,
        )

        self.gcsm: Optional["GlobalChatStreamManager"] = None

        # 静默事件缓存（避免每次判断都查数据库）
        self._silence_cache: Optional[Dict[str, Any]] = None
        self._silence_cache_ts: float = 0.0
        self._silence_cache_ttl: float = 60 * 60 # 1h 内复用缓存

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

    def set_gcsm_ref(self, gcsm: "GlobalChatStreamManager") -> None:
        """注入 GCSM 引用（启动后调用）。"""
        self.gcsm = gcsm
        if hasattr(self, 'reminder_dispatcher'):
            self.reminder_dispatcher.gcsm = gcsm

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
        try:
            await self.event_store.ensure_holidays()
        except Exception as e:
            self.logger.warning(f"Failed to ensure holidays: {e}")

        await self._fetch_and_process()

        last_fetch_time = time.time()

        while not self._stop_event.is_set():
            now = time.time()

            if now - last_fetch_time >= self.fetch_interval:
                await self._fetch_and_process()
                last_fetch_time = now

            await self.reminder_dispatcher.dispatch_all_due() # 派发提醒给用户

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.check_interval)
                break
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
            parsed_events = await self.parser.parse_dynamics(raw_items)

            for evt in parsed_events:
                evt["event_type"] = self._map_old_event_type(evt.get("event_type", "general"))
                evt.setdefault("source", "bilibili")
                evt.setdefault("is_recurring", False)
                evt.setdefault("is_personal", False)
                await self.event_store.add_event(evt)

            self.logger.info(f"Processed {len(parsed_events)} new event(s) from dynamics")
        except Exception as e:
            self.logger.error(f"Error in fetch_and_process: {e}")

    @staticmethod
    def _map_old_event_type(old_type: str) -> str:
        mapping = {
            "concert": UnifiedEventType.CONCERT.value,
            "collaboration": UnifiedEventType.GENERAL.value,
            "livestream": UnifiedEventType.LIVESTREAM.value,
            "release": UnifiedEventType.GENERAL.value,
            "anniversary": UnifiedEventType.ANNIVERSARY.value,
            "general": UnifiedEventType.GENERAL.value,
        }
        return mapping.get(old_type, UnifiedEventType.GENERAL.value)

    # ── 静默判断 ─────────────────────────────────────────────

    def is_silence_period(self) -> bool:
        """当前是否处于演唱会的静默时段内（带缓存，委托 get_silence_event）。"""
        return self.get_silence_event() is not None

    def get_silence_event(self) -> Optional[Dict[str, Any]]:
        """返回当前正在静默的演唱会事件（带 30s 内存缓存）。"""
        now_ts = time.monotonic()
        if self._silence_cache is not None and (now_ts - self._silence_cache_ts) < self._silence_cache_ttl:
            # 缓存命中但需用当前时间重判：演唱会可能在缓存后结束
            start_dt = self._silence_cache.get("start_datetime")
            end_dt = self._silence_cache.get("end_datetime")
            now = datetime.now()
            if start_dt and self._in_silence_range(start_dt, end_dt, now):
                return self._silence_cache
            else:
                # 已脱离静默，清除缓存
                self._silence_cache = None

        now = datetime.now()
        for event_dict in self.event_store.get_events_by_type(UnifiedEventType.CONCERT.value):
            start_dt = event_dict.get("start_datetime")
            if not start_dt:
                continue
            if self._in_silence_range(start_dt, event_dict.get("end_datetime"), now):
                self._silence_cache = event_dict
                self._silence_cache_ts = now_ts
                return event_dict

        self._silence_cache = None
        return None

    def _in_silence_range(
        self,
        start_dt: datetime,
        end_dt: Optional[datetime],
        now: datetime,
    ) -> bool:
        """判断 now 是否在 start_dt - pre 到 end_dt + post 的范围内。"""
        pre = start_dt - timedelta(minutes=self.silence_pre_minutes)
        if end_dt:
            post = end_dt + timedelta(minutes=self.silence_post_minutes)
        else:
            post = start_dt + timedelta(hours=4)
        return pre <= now <= post

    # ── 上下文提供 ─────────────────────────────────────────────

    def get_active_context(self, user_id: str = "") -> str:
        """返回应注入对话的近期活动摘要文本（提供给 TopicReplier）。"""
        return self.context_provider.get_context(user_id=user_id)

    # ── 手动触发接口 ─────────────────────────────────────────

    async def manual_fetch(self) -> Dict[str, Any]:
        """手动触发一次拉取（供 API/调试使用）。"""
        await self._fetch_and_process()
        return {"status": "ok"}

    def get_events(self, event_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """查询事件列表。"""
        if event_type:
            return self.event_store.get_events_by_type(event_type)
        return self.event_store.get_all_events()
