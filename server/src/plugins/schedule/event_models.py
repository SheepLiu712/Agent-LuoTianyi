"""
数据模型：统一事件类型、触发条件定义，以及与数据库 Event 模型的转换。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import  date 
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from src.utils.logger import get_logger
from src.utils.lunar_date import get_lunar_mmdd, get_holiday_name
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from src.database.sql_database import Event

logger = get_logger(__name__)


class UnifiedEventType(str, Enum):
    """统一事件类型（覆盖 TODO.md 中的所有事件类型）。"""
    CONCERT = "concert"               # 洛天依演唱会/线下演出
    LIVESTREAM = "livestream"         # 洛天依直播
    DYNAMIC = "dynamic"               # 洛天依 B站/微博 动态
    TRAVEL = "travel"                 # 洛天依旅游（citywalk）
    NEW_SONG = "new_song"             # 洛天依学会新歌
    HOLIDAY = "holiday"               # 节假日（通用）
    BIRTHDAY = "birthday"             # 用户生日
    ANNIVERSARY = "anniversary"       # 用户纪念日
    GENERAL = "general"               # 其他一般事件


@dataclass
class OfficialDynamic:
    uid: str
    account_name: str
    platform: str
    dynamic_id: str
    dynamic_type: str
    content: str
    raw_content: str
    pics: List[str]
    publish_time: str
    source_url: str


# ── 触发条件定义 ──────────────────────────────────────
# 每个事件类型对应的触发条件（触发时间点）

TRIGGER_CONDITIONS: Dict[UnifiedEventType, List[str]] = {
    UnifiedEventType.CONCERT: [
        "7_days_before",     # 提前7天
        "1_day_before",      # 提前1天
        "day_of_event",      # 当天
        "1_day_after",       # 第二天（回顾）
    ],
    UnifiedEventType.LIVESTREAM: [
        "1_hour_before",     # 提前1小时
        "day_of_event",      # 当天
    ],
    UnifiedEventType.DYNAMIC: [
        "day_of_event",      # 动态发布当天
    ],
    UnifiedEventType.TRAVEL: [
        "1_day_after",       # 第二天
    ],
    UnifiedEventType.NEW_SONG: [
        "1_day_after",       # 第二天
    ],
    UnifiedEventType.HOLIDAY: [
        "day_of_event",      # 当天
    ],
    UnifiedEventType.BIRTHDAY: [
        "day_of_event",      # 当天
    ],
    UnifiedEventType.ANNIVERSARY: [
        "day_of_event",      # 当天
    ],
    UnifiedEventType.GENERAL: [
        "day_of_event",
    ],
}


def get_default_trigger_conditions(event_type: UnifiedEventType) -> List[str]:
    """获取事件类型对应的默认触发条件列表。"""
    return TRIGGER_CONDITIONS.get(event_type, ["day_of_event"])


def parse_trigger_conditions(raw: str) -> List[str]:
    """从数据库 JSON 字符串解析触发条件列表。"""
    try:
        return json.loads(raw) if raw else []
    except (json.JSONDecodeError, TypeError):
        return []


def serialize_trigger_conditions(conditions: List[str]) -> str:
    """将触发条件列表序列化为 JSON 字符串。"""
    return json.dumps(conditions, ensure_ascii=False)


# ── 触发条件检查 ──────────────────────────────────────

def _parse_mmdd(mmdd_str: str) -> Optional[Tuple[int, int]]:
    """解析 MM-DD 格式的日期字符串。"""
    try:
        parts = mmdd_str.split("-")
        return int(parts[0]), int(parts[1])
    except (IndexError, ValueError):
        return None


def check_trigger_condition(
    condition_key: str,
    event_start_date: Optional[date],
    event_end_date: Optional[date],
    event_date_mmdd: Optional[str],
    event_is_lunar: bool,
    event_is_recurring: bool,
    today: Optional[date] = None,
) -> bool:
    """
    检查某个触发条件在今天是否应被触发。
    根据的事件类型和触发条件，检查今天是否满足触发条件。
    """
    today = today or date.today()

    if event_is_lunar:
        # 农历日期：检查今天农历日期是否匹配
        if event_date_mmdd:
            lunar_today_mmdd = get_lunar_mmdd(today.year, today.month, today.day)
            if lunar_today_mmdd is None:
                return False
            target_mm = int(event_date_mmdd.split("-")[0])
            target_dd = int(event_date_mmdd.split("-")[1])
            today_lunar_mm = int(lunar_today_mmdd.split("-")[0])
            today_lunar_dd = int(lunar_today_mmdd.split("-")[1])

            if condition_key == "day_of_event":
                return target_mm == today_lunar_mm and target_dd == today_lunar_dd
            # 对农历日期，提前/延后检查较复杂，仅精确匹配当天
            return False
        return False

    if event_date_mmdd and event_is_recurring:
        # 周期性事件（基于 MM-DD）
        parsed = _parse_mmdd(event_date_mmdd)
        if parsed is None:
            return False
        target_mm, target_dd = parsed
        try:
            target_date = date(today.year, target_mm, target_dd)
        except ValueError:
            return False
        return _check_days_offset_condition(condition_key, target_date, today)

    # 非周期性事件（基于具体日期）
    return _check_days_offset_condition(condition_key, event_start_date, today)


def _check_days_offset_condition(
    condition_key: str,
    target_date: Optional[date],
    today: date,
) -> bool:
    """检查日期偏移条件。"""
    if target_date is None:
        return False

    days_diff = (target_date - today).days

    condition_map = {
        "7_days_before": (days_diff == 7),
        "3_days_before": (days_diff == 3),
        "1_day_before": (days_diff == 1),
        "day_of_event": (days_diff == 0),
        "1_day_after": (days_diff == -1),
        "1_hour_before": (days_diff == 0),  # 当天，精确时间由调度频率保障
    }

    return condition_map.get(condition_key, False)


# ── 事件类型中文名 ──────────────────────────────────────

EVENT_TYPE_CN_MAP = {
    UnifiedEventType.CONCERT: "演唱会",
    UnifiedEventType.LIVESTREAM: "直播",
    UnifiedEventType.DYNAMIC: "动态",
    UnifiedEventType.TRAVEL: "旅游",
    UnifiedEventType.NEW_SONG: "新歌",
    UnifiedEventType.HOLIDAY: "节日",
    UnifiedEventType.BIRTHDAY: "生日",
    UnifiedEventType.ANNIVERSARY: "纪念日",
    UnifiedEventType.GENERAL: "活动",
}


def get_event_type_cn(event_type: UnifiedEventType) -> str:
    return EVENT_TYPE_CN_MAP.get(event_type, "活动")


# ── 数据库模型与业务模型的转换 ──────────────────────

def db_event_to_dict(event_row: "Event") -> Dict[str, Any]:
    """将数据库 Event 行转换为字典。"""

    return {
        "id": event_row.id,
        "event_type": event_row.event_type,
        "title": event_row.title,
        "description": event_row.description or "",
        "date_type": event_row.date_type or "solar",
        "date_mmdd": event_row.date_mmdd or "",
        "start_datetime": event_row.start_datetime,
        "end_datetime": event_row.end_datetime,
        "duration_minutes": event_row.duration_minutes,
        "trigger_conditions": parse_trigger_conditions(event_row.trigger_conditions or "[]"),
        "is_recurring": event_row.is_recurring or False,
        "is_personal": event_row.is_personal or False,
        "target_user_id": event_row.target_user_id or "",
        "source": event_row.source or "",
        "source_url": event_row.source_url or "",
        "source_platform": event_row.source_platform or "",
        "is_active": event_row.is_active or True,
        "created_at": event_row.created_at,
        "updated_at": event_row.updated_at,
    }
