"""
日期处理器：对话后处理中运行，与 _schedule_memory_write 同时进行。
- 使用独立 LLM 接口（不依赖 main_chat 的 ChatTemplate），通过 prompt_manager 控制 prompt
- 按置信度处理：>0.95 自动写库，<0.5 丢弃，之间创建 ExtractedTopic
- 提供 ImportantDate 表的读写接口
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from uuid import uuid4

from ..utils.llm.llm_module import LLMModule
from ..utils.llm.prompt_manager import PromptManager
from ..utils.logger import get_logger
from ..database import ImportantDate

if TYPE_CHECKING:
    from ..pipeline.topic_planner import ExtractedTopic
    from sqlalchemy.orm import Session

logger = get_logger(__name__)

# 置信度阈值
CONFIDENCE_AUTO_ADD = 0.95
CONFIDENCE_DISCARD = 0.5


# ── DateDetector 类 ──────────────────────────────────────


class DateDetector:
    """日期检测器，使用独立 LLM 接口 + prompt_manager 控制模板。"""

    def __init__(
        self,
        llm_config: Dict[str, Any],
        prompt_manager: PromptManager,
    ):
        self.prompt_manager = prompt_manager
        self.llm_client = LLMModule(llm_config["llm_module"], prompt_manager)

    async def detect(self, user_input: str, conversation_history: str = "") -> Optional[Dict[str, Any]]:
        if not user_input or not self.llm_client:
            return None
        
        # 启发式：只有user_input中包含“生日”才调用日期检测，减少不必要的LLM调用
        if "生日" not in user_input:
            return None

        try:
            result = await self.llm_client.generate_response(user_input = user_input, conversation_history=conversation_history, use_json=True)
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
    处理检测到的重要日期。

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
        saved = _save_important_date(open_sql_session, user_id, name, date_type, date_str, description)
        if saved:
            logger.info(f"Date {name}: confidence {confidence:.2f} >= {CONFIDENCE_AUTO_ADD}, auto-saved to DB")
            return True
        logger.warning(f"Date {name}: failed to save to DB")
        return None

    if reply_topic_callback:
        logger.info(f"Date {name}: confidence {confidence:.2f} in middle range, asking user")
        topic_text = (
            f"你注意到用户似乎提到了一个重要的日期。请问以下日期信息是否正确？\n" f"日期名称：{name}\n日期类型：{date_type}\n"
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


# ── 数据库操作 ──────────────────────────────────────────


def _save_important_date(
    open_sql_session,
    user_id: str,
    name: str,
    date_type: str,
    date_str: str,
    description: str,
) -> bool:
    if not date_str:
        logger.warning(f"Cannot save date without date string: {name}")
        return False

    db: "Session" = open_sql_session()
    try:
        existing = (
            db.query(ImportantDate)
            .filter(
                ImportantDate.user_id == user_id,
                ImportantDate.name == name,
            )
            .first()
        )
        if existing:
            existing.date_mmdd = date_str
            existing.date_type = date_type
            existing.description = description or existing.description
            existing.updated_at = datetime.now()
        else:
            db.add(
                ImportantDate(
                    user_id=user_id,
                    name=name,
                    date_type=date_type,
                    date_mmdd=date_str,
                    description=description,
                )
            )
        db.commit()
        logger.info(f"Saved important date for user {user_id}: {name} ({date_str})")
        return True
    except Exception as e:
        logger.error(f"Failed to save important date: {e}")
        db.rollback()
        return False
    finally:
        db.close()


def _make_topic(topic_content: str):
    from ..pipeline.topic_planner import ExtractedTopic

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
    """获取用户今天的重要日期。"""
    now = datetime.now()
    current_mm, current_dd = now.month, now.day

    db = open_sql_session()
    try:
        records = (
            db.query(ImportantDate)
            .filter(
                ImportantDate.user_id == user_id,
            )
            .all()
        )
        results = []
        for r in records:
            try:
                parts = r.date_mmdd.split("-")
                mm, dd = int(parts[0]), int(parts[1])
            except (IndexError, ValueError):
                continue
            if mm == current_mm and dd == current_dd:
                results.append(
                    {
                        "name": r.name,
                        "type": r.date_type,
                        "date": r.date_mmdd,
                        "description": r.description,
                    }
                )
        return results
    finally:
        db.close()
