"""
事件存储层：基于 JSON 文件的持久化存储。
提供增删改查、按状态/时间范围查询、自动过期等功能。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .event_models import EventStatus, EventType, ScheduleEvent
from src.utils.logger import get_logger


class EventStore:
    """
    JSON 文件事件存储。
    文件格式:
    {
        "events": { "<event_id>": <ScheduleEvent dict>, ... },
        "meta": { "version": 1, "last_fetch_time": "..." }
    }
    """

    def __init__(self, data_file: str = "data/schedule/events.json"):
        self.logger = get_logger(__name__)
        self.data_file = Path(data_file)
        self.data: Dict[str, Any] = {"events": {}, "meta": {"version": 1, "last_fetch_time": ""}}
        self._load()

    def _load(self) -> None:
        if not self.data_file.exists():
            return
        try:
            raw = json.loads(self.data_file.read_text(encoding="utf-8"))
            self.data = raw
            # 确保结构完整
            self.data.setdefault("events", {})
            self.data.setdefault("meta", {"version": 1, "last_fetch_time": ""})
            self.logger.info(f"Loaded {len(self.data['events'])} events from {self.data_file}")
        except Exception as e:
            self.logger.error(f"Failed to load events from {self.data_file}: {e}")
            self.data = {"events": {}, "meta": {"version": 1, "last_fetch_time": ""}}

    def _save(self) -> None:
        try:
            self.data_file.parent.mkdir(parents=True, exist_ok=True)
            self.data_file.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            self.logger.error(f"Failed to save events to {self.data_file}: {e}")

    def _list_events(self) -> List[ScheduleEvent]:
        events = []
        for d in self.data["events"].values():
            try:
                events.append(ScheduleEvent.from_dict(d))
            except Exception as e:
                self.logger.warning(f"Skipping malformed event: {e}")
        return events

    def _save_event(self, event: ScheduleEvent) -> None:
        self.data["events"][event.id] = event.to_dict()
        self._save()

    # ── 查询接口 ─────────────────────────────────────────────

    def get_all(self) -> List[ScheduleEvent]:
        return self._list_events()

    def get_by_id(self, event_id: str) -> Optional[ScheduleEvent]:
        d = self.data["events"].get(event_id)
        if d is None:
            return None
        return ScheduleEvent.from_dict(d)

    def get_by_status(self, status: EventStatus) -> List[ScheduleEvent]:
        return [e for e in self._list_events() if e.status == status]

    def get_upcoming(self) -> List[ScheduleEvent]:
        return sorted(
            [e for e in self._list_events() if e.status == EventStatus.UPCOMING],
            key=lambda e: e.start_time,
        )

    def get_ongoing(self) -> List[ScheduleEvent]:
        return [e for e in self._list_events() if e.status == EventStatus.ONGOING]

    def get_by_type(self, event_type: EventType) -> List[ScheduleEvent]:
        return [e for e in self._list_events() if e.event_type == event_type]

    def find_matching(
        self,
        title: str,
        start_time: str,
        threshold_days: int = 2,
    ) -> Optional[ScheduleEvent]:
        """
        根据标题和开始时间查找相似事件，用于去重。
        如果标题相似度较高且时间差在 threshold_days 内，认为是同一事件。
        """
        for event in self._list_events():
            if event.title == title and event.start_time == start_time:
                return event
            # 模糊匹配：标题包含关系 且 时间相近
            if (title in event.title or event.title in title) and event.start_time:
                try:
                    from datetime import date
                    d1 = datetime.fromisoformat(event.start_time).date()
                    d2 = datetime.fromisoformat(start_time).date()
                    if abs((d1 - d2).days) <= threshold_days:
                        return event
                except Exception:
                    pass
        return None

    def get_active_events(self, lookahead_days: int = 7) -> List[ScheduleEvent]:
        """获取未来 N 天内的活跃事件（upcoming/ongoing）。"""
        now = datetime.now()
        cutoff = now + __import__("datetime").timedelta(days=lookahead_days)
        result = []
        for e in self._list_events():
            if e.status not in {EventStatus.UPCOMING, EventStatus.ONGOING}:
                continue
            try:
                start = datetime.fromisoformat(e.start_time)
                if now <= start <= cutoff:
                    result.append(e)
            except Exception:
                pass
        return sorted(result, key=lambda e: e.start_time)

    def get_concert_silence_period(self) -> Optional[ScheduleEvent]:
        """如果当前处于某演唱会的静默时段内，返回该事件；否则返回 None。"""
        now = datetime.now()
        for e in self._list_events():
            if e.is_concert():
                # 复用 ScheduleEvent.is_silence_period，但需要接受配置参数
                if e.is_silence_period():
                    return e
        return None

    # ── 写入接口 ─────────────────────────────────────────────

    def add_event(self, event: ScheduleEvent) -> None:
        existing = self.find_matching(event.title, event.start_time)
        if existing:
            self.logger.info(f"Event already exists, updating: {event.title} (id={existing.id})")
            # 更新已有事件的信息
            existing.title = event.title
            existing.description = event.description
            existing.event_type = event.event_type
            existing.end_time = event.end_time
            existing.location = event.location
            existing.source_url = event.source_url
            existing.raw_content = event.raw_content
            existing.source_platform = event.source_platform
            existing.updated_at = datetime.now().isoformat()
            self._save_event(existing)
        else:
            event.id = event.id or str(uuid.uuid4())
            self._save_event(event)
            self.logger.info(f"Added new event: {event.title} (id={event.id}, type={event.event_type.value})")

    def update_event(self, event: ScheduleEvent) -> None:
        self._save_event(event)

    def mark_reminder_sent(self, event_id: str, advance_day: int, user_id: str = "") -> None:
        event = self.get_by_id(event_id)
        if event is None:
            return
        event.mark_reminder_sent(advance_day, user_id)
        self._save_event(event)

    def remove_event(self, event_id: str) -> bool:
        if event_id in self.data["events"]:
            del self.data["events"][event_id]
            self._save()
            return True
        return False

    # ── 自动维护 ─────────────────────────────────────────────

    def refresh_statuses(self) -> int:
        """根据当前时间自动更新所有事件的状态，返回变更数量。"""
        changed = 0
        for event in self._list_events():
            old_status = event.status
            event.update_status_by_time()
            if event.status != old_status:
                changed += 1
                self._save_event(event)
        if changed:
            self.logger.info(f"Refreshed {changed} event statuses")
        return changed

    def set_last_fetch_time(self, t: str) -> None:
        self.data["meta"]["last_fetch_time"] = t
        self._save()

    def get_last_fetch_time(self) -> str:
        return self.data["meta"].get("last_fetch_time", "")
