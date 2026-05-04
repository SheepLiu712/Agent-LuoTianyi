"""
活动上下文提供者：将近期活动信息注入 Agent 对话上下文，并控制提及频率。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from src.utils.logger import get_logger
from .event_models import EventStatus, EventType, ScheduleEvent
from .event_store import EventStore

logger = get_logger(__name__)


class ActivityContextProvider:
    """
    被 TopicReplier 调用，返回近期活动上下文文本。
    维护 per-user 提及记录，控制频率。
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

    def get_context(self, user_id: str = "") -> str:
        """
        返回应注入对话的近期活动摘要。
        如果 user_id 非空，会跳过最近已提及的活动（频率控制）。
        """
        events = self.event_store.get_active_events(lookahead_days=self.lookahead_days)
        if not events:
            return ""

        now_iso = datetime.now().isoformat()
        user_log = self._mention_log.get(user_id, {}) if user_id else {}
        lines: List[str] = ["[近期活动参考]"]
        added = 0

        for event in events[: self.max_context_events]:
            # 频率控制：如果该用户最近已提及过此事件，跳过
            if user_id and event.id in user_log:
                last = user_log[event.id]
                try:
                    last_dt = datetime.fromisoformat(last)
                    if (datetime.now() - last_dt).total_seconds() < self.mention_cooldown_hours * 3600:
                        continue
                except Exception:
                    pass

            start_str = event.start_time[:10] if event.start_time else "未知日期"
            type_names_cn = {
                EventType.CONCERT: "演唱会",
                EventType.COLLABORATION: "联动",
                EventType.LIVESTREAM: "直播",
                EventType.RELEASE: "新作品发布",
                EventType.ANNIVERSARY: "纪念日",
                EventType.GENERAL: "活动",
            }
            type_cn = type_names_cn.get(event.event_type, "活动")
            line = f"- {start_str} {type_cn}：「{event.title}」"
            if event.location:
                line += f"（{event.location}）"
            if event.description:
                line += f" {event.description[:60]}"
            lines.append(line)

            # 更新提及记录
            if user_id:
                if user_id not in self._mention_log:
                    self._mention_log[user_id] = {}
                self._mention_log[user_id][event.id] = now_iso
                added += 1

        if added == 0 and user_id:
            return ""  # 全部因频率控制被跳过
        if len(lines) <= 1:
            return ""

        self._save_mention_log()
        return "\n".join(lines)

    def get_silence_status(self) -> Optional[ScheduleEvent]:
        """返回当前静默中的演唱会事件（如有）。"""
        return self.event_store.get_concert_silence_period()

    def clear_mention_log(self, user_id: str = "") -> None:
        """清除提及记录（用于测试或用户重置）。"""
        if user_id:
            self._mention_log.pop(user_id, None)
        else:
            self._mention_log.clear()
        self._save_mention_log()

    def _load_mention_log(self) -> None:
        try:
            from pathlib import Path
            p = Path(self._log_file)
            if p.exists():
                self._mention_log = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Failed to load mention log: {e}")
            self._mention_log = {}

    def _save_mention_log(self) -> None:
        try:
            from pathlib import Path
            p = Path(self._log_file)
            p.parent.mkdir(parents=True, exist_ok=True)
            # 只保留最近 100 条记录
            trimmed = {}
            for uid in list(self._mention_log.keys())[:100]:
                trimmed[uid] = self._mention_log[uid]
            p.write_text(
                json.dumps(trimmed, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"Failed to save mention log: {e}")
