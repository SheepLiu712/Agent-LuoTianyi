"""
Schedule 插件包：统一日程管理系统。
提供事件定义、数据库存储、官方动态抓取、解析、触发派发、上下文注入等功能。
"""

from src.plugins.schedule.schedule_manager import ScheduleManager
from src.plugins.schedule.event_store import EventStore
from src.plugins.schedule.official_feed_fetcher import OfficialFeedFetcher
from src.plugins.schedule.event_parser import EventParser
from src.plugins.schedule.reminder_dispatcher import ReminderDispatcher
from src.plugins.schedule.activity_context_provider import ActivityContextProvider
from src.plugins.schedule.event_models import UnifiedEventType, get_event_type_cn, check_trigger_condition

__all__ = [
    "ScheduleManager",
    "EventStore",
    "OfficialFeedFetcher",
    "EventParser",
    "ReminderDispatcher",
    "ActivityContextProvider",
    "UnifiedEventType",
    "get_event_type_cn",
    "check_trigger_condition",
]
