"""
Schedule 插件包：真实日程系统。
提供洛天依官方动态拉取、事件解析、提醒派发、上下文注入等功能。
"""

from .schedule_manager import ScheduleManager
from .event_store import EventStore
from .official_feed_fetcher import OfficialFeedFetcher
from .event_parser import EventParser
from .reminder_dispatcher import ReminderDispatcher
from .activity_context_provider import ActivityContextProvider

__all__ = [
    "ScheduleManager",
    "EventStore",
    "OfficialFeedFetcher",
    "EventParser",
    "ReminderDispatcher",
    "ActivityContextProvider",
]
