"""
事件存储层：基于 SQL 数据库的持久化存储。
提供事件的增删改查、基于触发条件的查询、通知记录管理等功能。
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, date
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from src.utils.logger import get_logger
from src.utils.lunar_date import get_holiday_name, get_lunar_mmdd, lunar_to_solar, FIXED_SOLAR_HOLIDAYS, LUNAR_HOLIDAYS_MMDD, is_lunar_new_year_eve
from src.database.sql_database import Event, EventNotification
from .event_models import (
    UnifiedEventType,
    get_default_trigger_conditions,
    parse_trigger_conditions,
    serialize_trigger_conditions,
    check_trigger_condition,
    db_event_to_dict,
)

logger = get_logger(__name__)


class EventStore:
    """
    基于 SQL 数据库的事件存储系统。
    封装对 Event 和 EventNotification 表的操作。

    内部缓存策略：
    - get_all_events / get_events_due_for_trigger 的结果在当前自然日内不变，
      以次日 00:00 为自动过期时间。
    - 任何写操作（add / update / remove / mark_notified）会立即清空缓存。
    """

    def __init__(self, sql_session_factory: Callable[[], Session]):
        self.sql_session_factory = sql_session_factory
        self.logger = get_logger(__name__)
        # 日级缓存
        self._cache_lock = threading.Lock()
        self._all_events_cache: Optional[List[Dict[str, Any]]] = None
        self._due_events_cache: Optional[List[Tuple[Dict[str, Any], str]]] = None
        self._cache_date: Optional[date] = None

    # ── 缓存工具 ─────────────────────────────────────────────

    def _cache_valid(self) -> bool:
        """缓存是否在当前自然日内有效。"""
        return (
            self._cache_date is not None
            and self._cache_date == date.today()
        )

    def _invalidate_cache(self) -> None:
        with self._cache_lock:
            self._all_events_cache = None
            self._due_events_cache = None
            self._cache_date = None

    def _get_session(self) -> Session:
        return self.sql_session_factory()

    # ── 事件查询 ─────────────────────────────────────────────

    def get_all_events(self) -> List[Dict[str, Any]]:
        """获取所有活跃事件（带日级缓存，次日 00:00 自动刷新）。"""
        with self._cache_lock:
            if self._cache_valid() and self._all_events_cache is not None:
                return self._all_events_cache

        db = self._get_session()
        try:
            rows = db.query(Event).filter(Event.is_active == True).all()
            result = [db_event_to_dict(r) for r in rows]
            with self._cache_lock:
                self._all_events_cache = result
                self._cache_date = date.today()
            return result
        finally:
            db.close()

    def get_event_by_id(self, event_id: str) -> Optional[Dict[str, Any]]:
        """通过 ID 获取事件。"""
        db = self._get_session()
        try:
            row = db.query(Event).filter(Event.id == event_id, Event.is_active == True).first()
            return db_event_to_dict(row) if row else None
        finally:
            db.close()

    def get_events_by_type(self, event_type: str) -> List[Dict[str, Any]]:
        """按事件类型获取事件。"""
        db = self._get_session()
        try:
            rows = db.query(Event).filter(
                Event.event_type == event_type,
                Event.is_active == True,
            ).all()
            return [db_event_to_dict(r) for r in rows]
        finally:
            db.close()

    def get_events_for_user(self, user_id: str) -> List[Dict[str, Any]]:
        """获取对特定用户有意义的所有事件（公开事件 + personal事件）。"""
        db = self._get_session()
        try:
            rows = db.query(Event).filter(
                Event.is_active == True,
                (Event.is_personal == False) | (Event.target_user_id == user_id),
            ).all()
            return [db_event_to_dict(r) for r in rows]
        finally:
            db.close()

    def find_matching_event(
        self,
        title: str,
        start_datetime: Optional[datetime] = None,
        date_mmdd: Optional[str] = None,
        threshold_days: int = 2,
    ) -> Optional[Dict[str, Any]]:
        """查找匹配的事件（去重用）。"""
        db = self._get_session()
        try:
            rows = (
                db.query(Event)
                .filter(Event.title == title, Event.is_active == True)
                .all()
            )
            for row in rows:
                if start_datetime and row.start_datetime:
                    diff = abs((row.start_datetime - start_datetime).days)
                    if diff <= threshold_days:
                        return db_event_to_dict(row)
                if date_mmdd and row.date_mmdd == date_mmdd:
                    return db_event_to_dict(row)
            return None
        finally:
            db.close()

    def get_events_due_for_trigger(
        self,
        today: Optional[date] = None,
    ) -> List[tuple]:
        """
        获取今天需要触发通知的所有事件（带日级缓存，次日 00:00 自动刷新）。
        返回 List[Tuple[Dict[str, Any], str]]，每条记录包含 (event_dict, trigger_key)。
        """
        today = today or date.today()
        with self._cache_lock:
            if self._cache_valid() and self._due_events_cache is not None:
                return self._due_events_cache

        db = self._get_session()
        try:
            rows = db.query(Event).filter(Event.is_active == True).all()
            due_events = []
            for row in rows:
                conditions = parse_trigger_conditions(row.trigger_conditions or "[]")
                event_start_date = row.start_datetime.date() if row.start_datetime else None
                event_end_date = row.end_datetime.date() if row.end_datetime else None
                is_lunar = row.date_type == "lunar"

                for condition_key in conditions:
                    if check_trigger_condition(
                        condition_key=condition_key,
                        event_start_date=event_start_date,
                        event_end_date=event_end_date,
                        event_date_mmdd=row.date_mmdd,
                        event_is_lunar=is_lunar,
                        event_is_recurring=row.is_recurring or False,
                        today=today,
                    ):
                        due_events.append((db_event_to_dict(row), condition_key))
                        break  # 同一事件只需触发一次触发条件
            with self._cache_lock:
                self._due_events_cache = due_events
                self._cache_date = date.today()
            return due_events
        finally:
            db.close()

    # ── 事件写入 ─────────────────────────────────────────────

    def add_event(self, event_data: Dict[str, Any]) -> Optional[str]:
        """添加新事件到数据库。如果已存在匹配事件则更新。"""
        title = event_data.get("title", "")
        start_datetime = event_data.get("start_datetime")
        date_mmdd = event_data.get("date_mmdd")

        existing = self.find_matching_event(title, start_datetime, date_mmdd)
        if existing:
            self.logger.info(f"Event already exists, updating: {title} (id={existing['id']})")
            self._update_event(existing["id"], event_data)
            self._invalidate_cache()
            return existing["id"]

        db = self._get_session()
        try:
            # ...existing code...
            event_type = event_data.get("event_type", UnifiedEventType.GENERAL.value)
            try:
                evt_enum = UnifiedEventType(event_type)
            except ValueError:
                evt_enum = UnifiedEventType.GENERAL
            trigger_conditions = event_data.get(
                "trigger_conditions",
                get_default_trigger_conditions(evt_enum),
            )

            new_event = Event(
                id=event_data.get("id", str(uuid.uuid4())),
                event_type=event_type,
                title=title,
                description=event_data.get("description", ""),
                date_type=event_data.get("date_type", "solar"),
                date_mmdd=date_mmdd,
                start_datetime=start_datetime,
                end_datetime=event_data.get("end_datetime"),
                duration_minutes=event_data.get("duration_minutes"),
                trigger_conditions=serialize_trigger_conditions(
                    trigger_conditions
                    if isinstance(trigger_conditions, list)
                    else get_default_trigger_conditions(evt_enum)
                ),
                is_recurring=event_data.get("is_recurring", False),
                is_personal=event_data.get("is_personal", False),
                target_user_id=event_data.get("target_user_id"),
                source=event_data.get("source", ""),
                source_url=event_data.get("source_url", ""),
                source_platform=event_data.get("source_platform", ""),
            )
            db.add(new_event)
            db.commit()
            self._invalidate_cache()
            self.logger.info(
                f"Added new event: {title} (id={new_event.id}, type={event_type})"
            )
            return new_event.id
        except Exception as e:
            db.rollback()
            self.logger.error(f"Failed to add event: {e}")
            return None
        finally:
            db.close()

    def _update_event(self, event_id: str, event_data: Dict[str, Any]) -> None:
        """更新已有事件。"""
        db = self._get_session()
        try:
            row = db.query(Event).filter(Event.id == event_id).first()
            if row is None:
                return
            for key, value in event_data.items():
                if hasattr(row, key) and value is not None:
                    if key == "trigger_conditions" and isinstance(value, list):
                        setattr(row, key, serialize_trigger_conditions(value))
                    elif key == "id":
                        continue
                    else:
                        setattr(row, key, value)
            row.updated_at = datetime.now()
            db.commit()
            self._invalidate_cache()
        except Exception as e:
            db.rollback()
            self.logger.error(f"Failed to update event {event_id}: {e}")
        finally:
            db.close()

    def remove_event(self, event_id: str) -> bool:
        """软删除事件（标记为不活跃）。"""
        db = self._get_session()
        try:
            row = db.query(Event).filter(Event.id == event_id).first()
            if row:
                row.is_active = False
                row.updated_at = datetime.now()
                db.commit()
                self._invalidate_cache()
                return True
            return False
        except Exception as e:
            db.rollback()
            self.logger.error(f"Failed to remove event {event_id}: {e}")
            return False
        finally:
            db.close()

    # ── 过期事件清理 ─────────────────────────────────────────

    def purge_expired_events(self, today: Optional[date] = None) -> int:
        """
        清理已过期的事件：将 is_active 标记为 False。

        规则：
        - 周期性事件（is_recurring=True）：永不过期，不清除
        - 非周期性事件：
          - 有 end_datetime：end_datetime < today → 过期
          - 只有 start_datetime：start_datetime + 1 天 < today → 过期
          - 只有 date_mmdd（无具体日期）：保留（无法判定年份）
        - 保留 source="user" 的用户个人事件（生日/纪念日常年有效）
        """
        today = today or date.today()
        db = self._get_session()
        purged = 0
        try:
            rows = (
                db.query(Event)
                .filter(
                    Event.is_active == True,
                    Event.is_recurring == False,
                    Event.source != "user",
                )
                .all()
            )
            for row in rows:
                expired = False
                if row.end_datetime is not None:
                    if row.end_datetime.date() < today:
                        expired = True
                elif row.start_datetime is not None:
                    # 给一天缓冲，避免当天的事件被误清
                    if row.start_datetime.date() + __import__("datetime").timedelta(days=1) < today:
                        expired = True
                # 仅有 date_mmdd 无具体 datetime 的，跳过不清除

                if expired:
                    row.is_active = False
                    row.updated_at = datetime.now()
                    purged += 1

            if purged:
                db.commit()
                self._invalidate_cache()
                self.logger.info(f"Purged {purged} expired event(s)")
        except Exception as e:
            db.rollback()
            self.logger.error(f"Failed to purge expired events: {e}")
        finally:
            db.close()
        return purged

    # ── 预先写入固定节假日 ────────────────────────────────

    def ensure_holidays(self, years: Optional[List[int]] = None) -> int:
        """
        确保指定年份的常见节假日已被写入数据库。
        返回新增的节假日数量。
        """
        if years is None:
            current_year = datetime.now().year
            years = [current_year, current_year + 1] # 默认确保当前年和下一年的节假日

        added = 0
        for year in years:
            # 公历固定节日
            for mmdd, (name, desc) in FIXED_SOLAR_HOLIDAYS.items():
                month, day = int(mmdd.split("-")[0]), int(mmdd.split("-")[1])
                try:
                    d = date(year, month, day)
                except ValueError:
                    continue
                existing = self.find_matching_event(name, date_mmdd=f"{month:02d}-{day:02d}")
                if existing:
                    continue
                self.add_event({
                    "title": name,
                    "description": desc,
                    "event_type": UnifiedEventType.HOLIDAY.value,
                    "date_mmdd": f"{month:02d}-{day:02d}",
                    "date_type": "solar",
                    "is_recurring": True,
                    "source": "system",
                })
                added += 1

            # 农历节日
            for lunar_mmdd, (name, desc) in LUNAR_HOLIDAYS_MMDD.items():
                l_month, l_day = int(lunar_mmdd.split("-")[0]), int(lunar_mmdd.split("-")[1])
                solar = lunar_to_solar(year, l_month, l_day)
                if solar is None:
                    continue
                sol_year, sol_month, sol_day = solar
                existing = self.find_matching_event(name, date_mmdd=f"{l_month:02d}-{l_day:02d}")
                if existing:
                    continue
                self.add_event({
                    "title": name,
                    "description": desc,
                    "event_type": UnifiedEventType.HOLIDAY.value,
                    "date_mmdd": f"{l_month:02d}-{l_day:02d}",
                    "date_type": "lunar",
                    "is_recurring": True,
                    "source": "system",
                })
                added += 1

            # 特判除夕
            for month in range(1, 13):
                for day in range(1, 32):
                    try:
                        check_date = date(year, month, day)
                    except ValueError:
                        continue
                    if is_lunar_new_year_eve(year, month, day):
                        lunar_mmdd = get_lunar_mmdd(year, month, day)
                        if lunar_mmdd:
                            existing = self.find_matching_event("除夕夜", date_mmdd=lunar_mmdd)
                            if existing:
                                continue
                            self.add_event({
                                "title": "除夕夜",
                                "description": "除夕夜",
                                "event_type": UnifiedEventType.HOLIDAY.value,
                                "date_mmdd": lunar_mmdd,
                                "date_type": "lunar",
                                "is_recurring": True,
                                "source": "system",
                            })
                            added += 1

        if added:
            self.logger.info(f"Ensured {added} holiday events for years {years}")
        return added

    # ── 通知记录管理 ─────────────────────────────────────

    def is_notified(self, event_id: str, user_id: str, trigger_key: str) -> bool:
        """检查用户对某事件的某个触发条件是否已通知过。"""
        db = self._get_session()
        try:
            existing = (
                db.query(EventNotification)
                .filter(
                    EventNotification.event_id == event_id,
                    EventNotification.user_id == user_id,
                    EventNotification.trigger_key == trigger_key,
                )
                .first()
            )
            return existing is not None
        finally:
            db.close()

    def mark_notified(self, event_id: str, user_id: str, trigger_key: str) -> None:
        """标记用户对某事件的某个触发条件已通知（并刷新缓存）。"""
        if self.is_notified(event_id, user_id, trigger_key):
            return
        db = self._get_session()
        try:
            notification = EventNotification(
                event_id=event_id,
                user_id=user_id,
                trigger_key=trigger_key,
            )
            db.add(notification)
            db.commit()
            self._invalidate_cache()
        except Exception as e:
            db.rollback()
            self.logger.warning(f"Failed to mark notification: {e}")
        finally:
            db.close()
