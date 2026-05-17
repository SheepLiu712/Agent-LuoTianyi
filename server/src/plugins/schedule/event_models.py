"""
数据模型：ScheduleEvent 及相关枚举。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class EventType(str, Enum):
    COLLABORATION = "collaboration"   # 品牌联动/合作
    CONCERT = "concert"                # 演唱会/线下演出
    LIVESTREAM = "livestream"         # 直播/线上活动
    RELEASE = "release"                # 新歌/专辑发布
    ANNIVERSARY = "anniversary"        # 周年庆/纪念日
    GENERAL = "general"               # 一般公告


class EventStatus(str, Enum):
    UPCOMING = "upcoming"             # 即将开始
    ONGOING = "ongoing"               # 进行中
    ENDED = "ended"                   # 已结束
    CANCELLED = "cancelled"           # 已取消


@dataclass
class ScheduleEvent:
    id: str                           # UUID
    event_type: EventType              # 事件类型
    title: str                        # 事件标题
    description: str                  # 详细描述
    start_time: str                   # ISO 8601 时间字符串
    end_time: Optional[str]           # ISO 8601 时间字符串，可为空
    location: str = ""                # 活动地点
    source_url: str = ""              # 来源链接
    source_platform: str = ""          # bilibili / weibo
    raw_content: str = ""             # 原始动态内容
    status: EventStatus = EventStatus.UPCOMING
    reminder_sent: bool = False       # 是否已发送主提醒
    reminder_details: Dict[str, Any] = field(default_factory=dict)  # per-user 提醒记录
    created_at: str = ""             # ISO 8601
    updated_at: str = ""             # ISO 8601

    def __post_init__(self):
        now = datetime.now().isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["event_type"] = self.event_type.value
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ScheduleEvent":
        d = dict(d)
        d["event_type"] = EventType(d.get("event_type", "general"))
        d["status"] = EventStatus(d.get("status", "upcoming"))
        d.setdefault("reminder_sent", False)
        d.setdefault("reminder_details", {})
        d.setdefault("location", "")
        d.setdefault("source_url", "")
        d.setdefault("source_platform", "")
        d.setdefault("raw_content", "")
        return cls(**d)

    @property
    def start_datetime(self) -> Optional[datetime]:
        try:
            return datetime.fromisoformat(self.start_time)
        except Exception:
            return None

    @property
    def end_datetime(self) -> Optional[datetime]:
        if not self.end_time:
            return None
        try:
            return datetime.fromisoformat(self.end_time)
        except Exception:
            return None

    def is_concert(self) -> bool:
        return self.event_type == EventType.CONCERT

    def is_silence_period(self, pre_minutes: int = 30, post_minutes: int = 60) -> bool:
        """判断当前是否处于演唱会的静默时段内。"""
        if not self.is_concert():
            return False
        start = self.start_datetime
        end = self.end_datetime
        if start is None:
            return False
        now = datetime.now()
        pre = start - __import__("datetime").timedelta(minutes=pre_minutes)
        if end:
            post = end + __import__("datetime").timedelta(minutes=post_minutes)
        else:
            post = start + __import__("datetime").timedelta(hours=4)
        return pre <= now <= post

    def should_send_reminder(self, advance_days: List[int], user_id: str = "") -> bool:
        """
        判断是否应该发送提醒：
        - advance_days: 提前天数列表，如 [3, 1, 0]
        - user_id: 如果提供，检查 per-user 是否已提醒过
        """
        start = self.start_datetime
        if start is None:
            return False
        now = datetime.now().date()
        start_date = start.date()
        days_diff = (start_date - now).days

        if days_diff not in advance_days:
            return False

        if user_id:
            key = f"user_{user_id}"
            sent_days = self.reminder_details.get(key, [])
            if days_diff in sent_days:
                return False
        else:
            if self.reminder_sent and days_diff == advance_days[0]:
                return False

        return True

    def mark_reminder_sent(self, advance_day: int, user_id: str = "") -> None:
        if user_id:
            key = f"user_{user_id}"
            if key not in self.reminder_details:
                self.reminder_details[key] = []
            if advance_day not in self.reminder_details[key]:
                self.reminder_details[key].append(advance_day)
        else:
            self.reminder_sent = True
        self.updated_at = datetime.now().isoformat()

    def update_status_by_time(self) -> None:
        """根据当前时间自动更新状态。"""
        now = datetime.now()
        start = self.start_datetime
        end = self.end_datetime

        if start and now < start:
            self.status = EventStatus.UPCOMING
        elif end and now > end:
            self.status = EventStatus.ENDED
        elif start and now >= start:
            self.status = EventStatus.ONGOING
        self.updated_at = now.isoformat()
