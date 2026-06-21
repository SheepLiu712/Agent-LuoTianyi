"""
日期处理器：对话后处理中运行，与 _schedule_memory_write 同时进行。
- 使用独立 LLM 接口，通过 prompt_manager 控制 prompt
- 按置信度处理：>0.95 自动写 Event 表，<0.5 丢弃，之间创建 ExtractedTopic
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from uuid import uuid4

from src.utils.llm.llm_module import LLMModule
from src.utils.llm.prompt_manager import PromptManager
from src.utils.logger import get_logger
from src.system.database import Event

if TYPE_CHECKING:
    from src.agent.chat.topic_planner import ExtractedTopic
    from sqlalchemy.orm import Session

logger = get_logger(__name__)

CONFIDENCE_AUTO_ADD = 0.95
CONFIDENCE_DISCARD = 0.5

# ── 日期类型 → Event.event_type 映射 ────────────────

_DATE_TYPE_MAP = {
    "生日": "birthday",
    "纪念日": "anniversary",
    "节日": "holiday",
}
_DEFAULT_EVENT_TYPE = "anniversary"


# ── DateDetector 类 ──────────────────────────────────────


class DateDetector:
    """日期检测器，使用独立 LLM 接口 + prompt_manager 控制模板。"""

    def __init__(
        self,
        llm_config: Dict[str, Any],
        prompt_manager: PromptManager,
    ):
        self.prompt_manager = prompt_manager
        self.llm_client = LLMModule(llm_config, prompt_manager)

    async def detect(self, user_input: str, conversation_history: str = "") -> Optional[Dict[str, Any]]:
        if not user_input or not self.llm_client:
            return None

        if "生日" not in user_input:
            return None

        try:
            result = await self.llm_client.generate_response(
                user_input=user_input, conversation_history=conversation_history, use_json=True
            )
        except Exception as e:
            logger.warning(f"DateDetector LLM call failed: {e}")
            return None

        if not result:
            return None

        result = result.strip()
        if result.startswith("```"):
            lines = result.split("\n")
            result = "\n".join(lines[1:-1]).strip()

        try:
            data = json.loads(result)
            if not isinstance(data, dict):
                return None

            has_date = data.get("has_date", False)
            confidence = data.get("confidence", 0.0)
            if not has_date or confidence < 0.5:
                logger.debug(f"DateDetector: no date detected (confidence={confidence:.2f})")
                return None

            return {
                "name": data.get("name", ""),
                "type": data.get("type", "其他"),
                "date": data.get("date", ""),
                "description": data.get("description", ""),
                "confidence": float(confidence),
            }
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.warning(f"DateDetector: failed to parse LLM response: {e}")
            return None


# ── 置信度处理 ──────────────────────────────────────────


async def process_detected_date(
    date_info: Dict[str, Any],
    user_id: str,
    open_sql_session,
    reply_topic_callback,
) -> Optional[bool]:
    """
    处理检测到的重要日期，写入 Event 表。

    Returns:
        True=已自动添加, False=已丢弃, None=需用户确认
    """
    confidence = date_info.get("confidence", 0.0)
    name = date_info.get("name", "")
    date_str = date_info.get("date", "")
    date_type = date_info.get("type", "其他")
    description = date_info.get("description", "")

    if confidence < CONFIDENCE_DISCARD:
        logger.info(f"Date {name}: confidence {confidence:.2f} < {CONFIDENCE_DISCARD}, discarded")
        return False

    if confidence >= CONFIDENCE_AUTO_ADD and date_str:
        saved = _save_user_date_event(open_sql_session, user_id, name, date_type, date_str, description)
        if saved:
            logger.info(f"Date {name}: confidence {confidence:.2f} >= {CONFIDENCE_AUTO_ADD}, auto-saved to Event table")
            return True
        logger.warning(f"Date {name}: failed to save to Event table")
        return None

    if reply_topic_callback:
        logger.info(f"Date {name}: confidence {confidence:.2f} in middle range, asking user")
        topic_text = (
            f"你注意到用户似乎提到了一个重要的日期。请问以下日期信息是否正确？\n"
            f"日期名称：{name}\n日期类型：{date_type}\n"
        )
        if date_str:
            topic_text += f"具体日期：{date_str}\n"
        if description:
            topic_text += f"描述：{description}\n"
        topic_text += "\n如果正确请天依就会把它记住。"

        reply_topic_callback(_make_topic(topic_text))
        return None

    logger.info(f"Date {name}: confidence {confidence:.2f} in middle range but no callback, discarded")
    return None


# ── 数据库操作（Event 表）──────────────────────────────────


def _save_user_date_event(
    open_sql_session,
    user_id: str,
    name: str,
    date_type: str,
    date_str: str,
    description: str,
) -> bool:
    """将用户重要日期写入 Event 表（birthday / anniversary / holiday）。"""
    if not date_str:
        logger.warning(f"Cannot save date without date string: {name}")
        return False

    # 解析 MM-DD
    parts = date_str.split("-")
    if len(parts) < 2:
        logger.warning(f"Invalid date format: {date_str}")
        return False
    try:
        mm, dd = int(parts[0]), int(parts[1])
    except ValueError:
        logger.warning(f"Invalid date parts: {date_str}")
        return False

    event_type = _DATE_TYPE_MAP.get(date_type, _DEFAULT_EVENT_TYPE)

    db: "Session" = open_sql_session()
    try:
        # 查找是否已存在同名活跃事件
        existing = (
            db.query(Event)
            .filter(
                Event.event_type == event_type,
                Event.user_id == user_id,
                Event.title == name,
                Event.is_active == True,
            )
            .first()
        )
        now = datetime.now()
        if existing:
            existing.date_mmdd = f"{mm:02d}-{dd:02d}"
            existing.description = description or existing.description
            existing.updated_at = now
        else:
            db.add(Event(
                id=str(uuid4()),
                event_type=event_type,
                title=name,
                description=description,
                user_id=user_id,
                date_type="solar",
                date_mmdd=f"{mm:02d}-{dd:02d}",
                is_recurring=True,
                is_personal=True,
                target_user_id=user_id,
                source="user",
                trigger_conditions='["day_of_event"]',
            ))
        db.commit()
        logger.info(f"Saved user date event for user {user_id}: {name} ({date_str}) type={event_type}")
        return True
    except Exception as e:
        logger.error(f"Failed to save user date event: {e}")
        db.rollback()
        return False
    finally:
        db.close()


# ── 话题构建 ──────────────────────────────────────────


def _make_topic(topic_content: str):
    from src.agent.chat.topic_planner import ExtractedTopic

    return ExtractedTopic(
        topic_id=str(uuid4()),
        source_messages=[],
        topic_content=topic_content,
        memory_attempts=[],
        fact_constraints=[],
        sing_attempts=[],
        is_forced_from_incomplete=True,
    )


def get_today_important_dates(open_sql_session, user_id: str) -> List[Dict[str, Any]]:
    """从 Event 表获取用户今天的重要日期（生日/纪念日）。"""
    now = datetime.now()
    current_mm, current_dd = now.month, now.day

    db = open_sql_session()
    try:
        relevant_types = ("birthday", "anniversary")
        records = (
            db.query(Event)
            .filter(
                Event.event_type.in_(relevant_types),
                Event.user_id == user_id,
                Event.is_active == True,
            )
            .all()
        )
        results = []
        for r in records:
            if not r.date_mmdd:
                continue
            try:
                parts = r.date_mmdd.split("-")
                mm, dd = int(parts[0]), int(parts[1])
            except (IndexError, ValueError):
                continue
            if mm == current_mm and dd == current_dd:
                results.append({
                    "name": r.title,
                    "type": r.event_type,
                    "date": r.date_mmdd,
                    "description": r.description or "",
                })
        return results
    finally:
        db.close()
