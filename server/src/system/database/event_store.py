"""
事件存储层：基于 SQL 数据库的持久化存储。
提供事件的增删改查、基于触发条件的查询、通知记录管理等功能。
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, date
from typing import Any, Callable, Dict, List, Optional, Tuple, TYPE_CHECKING

from sqlalchemy.orm import Session

from src.utils.logger import get_logger
from src.utils.lunar_date import get_lunar_mmdd, lunar_to_solar, FIXED_SOLAR_HOLIDAYS, LUNAR_HOLIDAYS_MMDD, is_lunar_new_year_eve
from src.system.database.sql_database import Event, EventNotification
from src.system.database.redis_buffer import RedisBuffer
from src.utils.llm.llm_module import LLMModule
from src.system.database.event_models import (
    UnifiedEventType,
    get_default_trigger_conditions,
    parse_trigger_conditions,
    serialize_trigger_conditions,
    check_trigger_condition,
    db_event_to_dict,
)

if TYPE_CHECKING:
    from src.utils.llm_service import LLMService
    from sqlalchemy.orm import Session


class EventStore:
    """
    基于 SQL 数据库的事件存储系统。
    封装对 Event 和 EventNotification 表的操作。

    内部缓存策略：
    - get_all_events / get_events_due_for_trigger 的结果在当前自然日内不变，
      以次日 00:00 为自动过期时间。
    - 任何写操作（add / update / remove / mark_notified）会立即清空缓存。
    """

    def __init__(
        self,
        config: Dict[str, Any],
        sql_session_factory: Callable[[], Session],
        redis_buffer: RedisBuffer,
        llm_module: Optional[LLMModule] = None,
    ):
        self.config = config
        self.logger = get_logger(__name__)
        self.sql_session_factory = sql_session_factory
        _ = redis_buffer # not used now, but kept for future use
        self.llm_module = llm_module

        # 日级缓存
        self._cache_lock = threading.Lock()
        self._all_events_cache: Optional[List[Dict[str, Any]]] = None
        self._due_events_cache: Optional[List[Tuple[Dict[str, Any], str]]] = None
        self._cache_date: Optional[date] = None

    def create_llm_module(self, llm_service: "LLMService"):
        llm_module_config = self.config["llm_module"]
        self.llm_module = llm_service.register_llm_module("FindMatchingEvent", llm_module_config)

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

    # ── 去重匹配（精确 + LLM 双路径）────────────────────────

    def _find_matching_event_exact(
        self,
        title: str,
        start_datetime: Optional[datetime] = None,
        date_mmdd: Optional[str] = None,
        threshold_days: int = 2,
    ) -> Optional[Dict[str, Any]]:
        """精确标题匹配（LLM 不可用或 system 事件时的回退路径）。"""
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

    async def _find_matching_event_with_llm(
        self,
        title: str,
        description: str,
        event_type: str,
        start_datetime: Optional[datetime],
        date_mmdd: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        """
        LLM 驱动的模糊匹配：缩小候选集后用 LLM 判断是否同一事件。
        返回匹配的 event_dict（附带 _merged_description 字段），或 None。
        """
        if self.llm_module is None:
            return None

        # 1. 候选集缩小：同类型 + 同月 ±7 天
        db = self._get_session()
        try:
            candidates: List[Event] = []
            base_rows = (
                db.query(Event)
                .filter(
                    Event.event_type == event_type,
                    Event.is_active == True,
                )
                .all()
            )

            ref_date: Optional[date] = None
            if start_datetime:
                ref_date = start_datetime.date() if isinstance(start_datetime, datetime) else start_datetime
            elif date_mmdd:
                # 用 MM-DD 在当前年构造参考日期
                import datetime as _dt
                parts = date_mmdd.split("-")
                try:
                    ref_date = _dt.date(_dt.date.today().year, int(parts[0]), int(parts[1]))
                except (IndexError, ValueError):
                    pass

            window_start = ref_date - __import__("datetime").timedelta(days=7) if ref_date else None
            window_end = ref_date + __import__("datetime").timedelta(days=7) if ref_date else None

            for row in base_rows:
                row_date: Optional[date] = None
                if row.start_datetime:
                    row_date = row.start_datetime.date() if isinstance(row.start_datetime, datetime) else row.start_datetime
                elif row.date_mmdd and ref_date:
                    parts2 = row.date_mmdd.split("-")
                    try:
                        row_date = __import__("datetime").date(ref_date.year, int(parts2[0]), int(parts2[1]))
                    except (IndexError, ValueError):
                        pass
                if row_date and window_start and window_end and window_start <= row_date <= window_end:
                    candidates.append(row)

            if not candidates:
                self.logger.debug(f"LLM dedup: empty candidate set for '{title}', skipping LLM call")
                return None

            # 2. 构建 prompt
            candidate_lines: List[str] = []
            for c in candidates:
                c_start = c.start_datetime.isoformat() if c.start_datetime else ""
                candidate_lines.append(
                    f"  id={c.id} | {c.title} | {c.description or ''} | {c_start} | mmdd={c.date_mmdd or ''}"
                )
            candidates_text = "\n".join(candidate_lines)

            type_cn = {
                "concert": "演唱会", "livestream": "直播", "dynamic": "动态",
                "travel": "旅游", "new_song": "新歌", "holiday": "节日",
                "birthday": "生日", "anniversary": "纪念日", "general": "活动",
            }.get(event_type, event_type)

            prompt = (
                f"你是一个活动去重助手。判断以下新事件是否与任何已有事件指向同一场真实活动。\n\n"
                f"【新事件】\n"
                f"- 标题: {title}\n"
                f"- 描述: {description}\n"
                f"- 类型: {type_cn}\n"
                f"- 时间: {start_datetime.isoformat() if start_datetime else '无'}\n"
                f"- 日期(MM-DD): {date_mmdd or '无'}\n\n"
                f"【已有事件列表】\n{candidates_text}\n\n"
                f"判断标准：\n"
                f"1. 同一场演唱会/直播/活动的不同宣传帖为重复\n"
                f"2. 不同场次/不同活动为不重复\n"
                f"3. 若重复，将新旧描述合并压缩为一句话（30字以内）\n\n"
                f"输出 JSON（严格格式）：\n"
                f'{{"match": true/false, "matched_id": "事件ID或空字符串", "merged_description": "合并描述或空字符串"}}'
            )

            # 3. 调用 LLM
            try:
                resp = await self.llm_client.generate_response(prompt, use_json=True)
                result = (resp or {}).get("content", "") if isinstance(resp, dict) else str(resp)
                if not result:
                    self.logger.warning("LLM dedup returned empty response, falling back to exact match")
                    return None
                result = result.strip()
            except Exception as e:
                self.logger.warning(f"LLM dedup call failed ({e}), falling back to exact match")
                return None

            # 4. 解析结果
            try:
                import json as _json
                parsed = _json.loads(result)
                if not isinstance(parsed, dict):
                    return None
                if not parsed.get("match"):
                    self.logger.debug(f"LLM dedup: no match for '{title}'")
                    return None
                matched_id = parsed.get("matched_id", "")
                merged_desc = parsed.get("merged_description", "")
                if not matched_id:
                    return None

                # 5. 确认匹配事件确实存在
                matched_row = db.query(Event).filter(Event.id == matched_id, Event.is_active == True).first()
                if matched_row is None:
                    self.logger.warning(f"LLM matched non-existent event id={matched_id}")
                    return None

                matched_dict = db_event_to_dict(matched_row)
                matched_dict["_merged_description"] = merged_desc if merged_desc else description
                self.logger.info(
                    f"LLM dedup matched: '{title}' → existing '{matched_row.title}' (id={matched_id})"
                )
                self.logger.debug(f"Description merged: '{matched_row.description}' + '{description}' → '{merged_desc}'")
                return matched_dict

            except (ValueError, _json.JSONDecodeError) as e:
                self.logger.warning(f"LLM dedup returned invalid JSON ({e}), falling back to exact match")
                return None
        finally:
            db.close()

    async def find_matching_event(
        self,
        title: str,
        start_datetime: Optional[datetime] = None,
        date_mmdd: Optional[str] = None,
        description: str = "",
        event_type: str = "general",
        source: str = "",
        threshold_days: int = 2,
    ) -> Optional[Dict[str, Any]]:
        """
        查找匹配的事件（去重用）。
        - source 为 "system" 时直接走精确匹配（节假日去重）
        - LLM 可用时走 LLM 模糊匹配；不可用时降级精确匹配
        """
        # system 事件（节假日等）走精确匹配，避免不必要的 LLM 调用
        if source == "system" or self.llm_client is None:
            return self._find_matching_event_exact(title, start_datetime, date_mmdd, threshold_days)

        # LLM 路径
        result = await self._find_matching_event_with_llm(
            title=title,
            description=description,
            event_type=event_type,
            start_datetime=start_datetime,
            date_mmdd=date_mmdd,
        )
        if result is not None:
            return result

        # LLM 无匹配或降级 → 精确匹配兜底
        return self._find_matching_event_exact(title, start_datetime, date_mmdd, threshold_days)

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

    async def add_event(self, event_data: Dict[str, Any]) -> Optional[str]:
        """添加新事件到数据库。如果已存在匹配事件则更新。"""
        title = event_data.get("title", "")
        start_datetime = event_data.get("start_datetime")
        date_mmdd = event_data.get("date_mmdd")
        description = event_data.get("description", "")
        event_type = event_data.get("event_type", UnifiedEventType.GENERAL.value)
        source = event_data.get("source", "")

        existing = await self.find_matching_event(
            title=title,
            start_datetime=start_datetime,
            date_mmdd=date_mmdd,
            description=description,
            event_type=event_type,
            source=source,
        )
        if existing:
            merged_desc = existing.pop("_merged_description", None)
            self.logger.info(f"Event already exists, updating: {title} (id={existing['id']})")
            self._update_event(existing["id"], event_data, merged_description=merged_desc)
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

    def _update_event(
        self,
        event_id: str,
        event_data: Dict[str, Any],
        merged_description: Optional[str] = None,
    ) -> None:
        """
        更新已有事件。
        - 时间字段（start_datetime / end_datetime）始终以新值为准直接覆盖
        - 若提供 merged_description（LLM 合并结果），覆盖 description
        - 其他字段：新值覆盖
        """
        db = self._get_session()
        try:
            row = db.query(Event).filter(Event.id == event_id).first()
            if row is None:
                return
            # 先处理 description：优先使用 LLM 合并结果
            if merged_description:
                row.description = merged_description
            for key, value in event_data.items():
                if hasattr(row, key) and value is not None:
                    if key == "trigger_conditions" and isinstance(value, list):
                        setattr(row, key, serialize_trigger_conditions(value))
                    elif key in ("id", "description"):
                        # id 不可改；description 已在 merged_description 分支处理
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

    async def ensure_holidays(self, years: Optional[List[int]] = None) -> int:
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
                existing = await self.find_matching_event(name, date_mmdd=f"{month:02d}-{day:02d}", source="system")
                if existing:
                    break # 所有的节日都是统一加进去的，一个有重复，说明所有的都加过了
                await self.add_event({
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
                existing = await self.find_matching_event(name, date_mmdd=f"{l_month:02d}-{l_day:02d}", source="system")
                if existing:
                    continue
                await self.add_event({
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
                            existing = await self.find_matching_event("除夕夜", date_mmdd=lunar_mmdd, source="system")
                            if existing:
                                continue
                            await self.add_event({
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
