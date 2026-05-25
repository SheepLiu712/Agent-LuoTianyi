"""
活动上下文提供者：将近期活动信息注入 Agent 对话上下文，并控制提及频率。
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.utils.logger import get_logger
from src.utils.lunar_date import get_holiday_name
from .event_models import UnifiedEventType, get_event_type_cn, db_event_to_dict
from .event_store import EventStore

logger = get_logger(__name__)


class ActivityContextProvider:
    """
    被 TopicReplier 调用，返回近期活动上下文文本。
    维护 per-user 提及记录，控制频率。

    缓存策略：
    - get_context() 结果在同一天内不变，以次日 00:00 为过期点
    - 写入 mention_log 后会清空缓存
    """

    def __init__(
        self,
        event_store: EventStore,
        mention_cooldown_hours: int = 6,
        lookahead_days: int = 7,
        max_context_events: int = 5,
    ):
        self.event_store = event_store
        self.mention_cooldown_hours = mention_cooldown_hours
        self.lookahead_days = lookahead_days
        self.max_context_events = max_context_events
        # per-user 提及记录: {user_id: {event_id: last_mention_isoformat}}
        self._mention_log: Dict[str, Dict[str, str]] = {}
        self._log_file = "data/schedule/mention_log.json"
        self._load_mention_log()
        # 日级缓存
        self._cache_lock = threading.Lock()
        self._context_cache: Dict[str, str] = {}   # user_id → context_string
        self._cache_date: Optional[date] = None

    # ── 缓存工具 ─────────────────────────────────────────────

    def _cache_valid(self) -> bool:
        return self._cache_date is not None and self._cache_date == date.today()

    def _invalidate_cache(self) -> None:
        with self._cache_lock:
            self._context_cache.clear()
            self._cache_date = None

    def get_context(self, user_id: str = "") -> str:
        """
        返回应注入对话的近期活动摘要。
        仅注入演唱会/直播类事件（大型活动），限制在 lookahead_days 天内开始。
        结果带日级缓存（同一天返回相同结果）。
        """
        # 日级缓存
        with self._cache_lock:
            if self._cache_valid() and user_id in self._context_cache:
                return self._context_cache[user_id]

        all_events = self.event_store.get_all_events()
        if not all_events:
            return ""

        # 只筛选演唱会/直播类型事件
        relevant_types = {UnifiedEventType.CONCERT.value, UnifiedEventType.LIVESTREAM.value}
        now = datetime.now()
        cutoff = now + timedelta(days=self.lookahead_days)
        events = [
            e for e in all_events
            if e.get("event_type") in relevant_types
            and e.get("start_datetime") is not None
            and now <= e["start_datetime"] <= cutoff  # 只保留 7 天内开始的活动
        ]
        # 按开始日期排序
        events.sort(key=lambda e: e.get("start_datetime") or datetime.max)

        if not events:
            with self._cache_lock:
                self._context_cache[user_id] = ""
                self._cache_date = date.today()
            return ""

        now_iso = now.isoformat()
        user_log = self._mention_log.get(user_id, {}) if user_id else {}
        lines: List[str] = ["[近期活动参考]"]
        added = 0

        for event_dict in events[: self.max_context_events]:
            event_id = event_dict["id"]
            # 频率控制
            if user_id and event_id in user_log:
                last = user_log[event_id]
                try:
                    last_dt = datetime.fromisoformat(last)
                    if (now - last_dt).total_seconds() < self.mention_cooldown_hours * 3600:
                        continue
                except Exception:
                    pass

            start_dt = event_dict.get("start_datetime")
            start_str = start_dt.strftime("%m-%d") if start_dt else "未知日期"
            evt_type = UnifiedEventType(event_dict.get("event_type", UnifiedEventType.GENERAL.value))
            type_cn = get_event_type_cn(evt_type)
            line = f"- {start_str} {type_cn}：「{event_dict['title']}」"
            if event_dict.get("description"):
                line += f" - {event_dict['description'][:60]}"
            lines.append(line)

            if user_id:
                if user_id not in self._mention_log:
                    self._mention_log[user_id] = {}
                self._mention_log[user_id][event_id] = now_iso
                added += 1

        if added == 0 and user_id:
            with self._cache_lock:
                self._context_cache[user_id] = ""
                self._cache_date = date.today()
            return ""
        if len(lines) <= 1:
            with self._cache_lock:
                self._context_cache[user_id] = ""
                self._cache_date = date.today()
            return ""

        result = "\n".join(lines)
        with self._cache_lock:
            self._context_cache[user_id] = result
            self._cache_date = date.today()
        self._save_mention_log()
        return result

    def clear_mention_log(self, user_id: str = "") -> None:
        """清除提及记录（用于测试或用户重置）。"""
        if user_id:
            self._mention_log.pop(user_id, None)
        else:
            self._mention_log.clear()
        self._save_mention_log()

    def _load_mention_log(self) -> None:
        try:
            p = Path(self._log_file)
            if p.exists():
                self._mention_log = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Failed to load mention log: {e}")
            self._mention_log = {}

    def _save_mention_log(self) -> None:
        try:
            p = Path(self._log_file)
            p.parent.mkdir(parents=True, exist_ok=True)
            trimmed = {}
            for uid in list(self._mention_log.keys())[:100]:
                trimmed[uid] = self._mention_log[uid]
            p.write_text(
                json.dumps(trimmed, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"Failed to save mention log: {e}")
