"""
提醒派发器（独立模块，也可由 ScheduleManager 调用）。

职责：
- 扫描即将触发的事件
- 向所有在线用户推送提醒消息
- 维护 per-user 提醒记录，避免重复发送
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.utils.logger import get_logger
from .event_models import EventStatus, EventType, ScheduleEvent
from .event_store import EventStore

logger = get_logger(__name__)


class ReminderDispatcher:
    """将到期事件提醒推送给在线用户。"""

    def __init__(
        self,
        event_store: EventStore,
        service_hub_ref: Any,  # callable / obj with .gcsm
        advance_days_concert: List[int] = None,
        advance_days_general: List[int] = None,
    ):
        self.event_store = event_store
        self.service_hub_ref = service_hub_ref
        self.advance_days_concert = advance_days_concert or [3, 1, 0]
        self.advance_days_general = advance_days_general or [0]
        self.logger = get_logger(__name__)

    # ── 主入口 ────────────────────────────────────────

    async def dispatch_all_due(self) -> int:
        """
        扫描所有 upcoming 事件，向在线用户派发到期提醒。
        返回本次派发的提醒总数。
        """
        events = self.event_store.get_upcoming()
        total = 0
        for event in events:
            n = await self._dispatch_one_event(event)
            total += n
        if total:
            self.logger.info(f"Dispatched {total} reminder(s) in total")
        return total

    # ── 内部方法 ──────────────────────────────────────

    async def _dispatch_one_event(self, event: ScheduleEvent) -> int:
        """对单个事件，向所有符合条件的在线用户发送提醒。"""
        advance_days = (
            self.advance_days_concert
            if event.event_type == EventType.CONCERT
            else self.advance_days_general
        )
        now_date = datetime.now().date()
        if event.start_datetime is None:
            return 0
        days_diff = (event.start_datetime.date() - now_date).days
        if days_diff not in advance_days:
            return 0

        # 获取在线用户
        online_users = self._get_online_user_ids()
        sent = 0
        for user_id in online_users:
            if not event.should_send_reminder(advance_days, user_id):
                continue
            ok = await self._send_reminder_to_user(event, user_id, days_diff)
            if ok:
                event.mark_reminder_sent(days_diff, user_id)
                self.event_store.update_event(event)
                sent += 1
        return sent

    def _get_online_user_ids(self) -> List[str]:
        """从 GCSM 获取在线用户的 user_id 列表。"""
        try:
            gcsm = self._get_gcsm()
            if gcsm is None:
                return []
            # GCSM.user_streams 是 {user_id: ChatStream}
            return [
                uid
                for uid, stream in gcsm.user_streams.items()
                if stream and not stream.is_connection_lost()
            ]
        except Exception as e:
            self.logger.warning(f"Failed to get online users: {e}")
            return []

    def _get_gcsm(self) -> Optional[Any]:
        if self.service_hub_ref is None:
            return None
        try:
            return self.service_hub_ref.gcsm
        except Exception:
            return None

    async def _send_reminder_to_user(
        self, event: ScheduleEvent, user_id: str, days_diff: int
    ) -> bool:
        """向单个用户发送提醒（通过 ChatStream）。"""
        try:
            gcsm = self._get_gcsm()
            if gcsm is None:
                return False
            chat_stream = gcsm.user_streams.get(user_id)
            if chat_stream is None:
                return False
            if chat_stream.is_connection_lost():
                return False

            # 构造提醒文本
            if days_diff == 0:
                time_desc = "今天"
            elif days_diff == 1:
                time_desc = "明天"
            else:
                time_desc = f"{days_diff} 天后"

            type_names_cn = {
                EventType.CONCERT: "演唱会",
                EventType.COLLABORATION: "联动活动",
                EventType.LIVESTREAM: "直播",
                EventType.RELEASE: "新作品发布",
                EventType.ANNIVERSARY: "纪念活动",
                EventType.GENERAL: "活动",
            }
            type_name = type_names_cn.get(event.event_type, "活动")

            content = f"{time_desc}有{type_name}「{event.title}」"
            if event.location:
                content += f"，地点在{event.location}"
            content += "，记得关注哦~"

            # 构造 ExtractedTopic 送入 topic_replier
            from src.pipeline.topic_planner import ExtractedTopic
            import uuid

            topic = ExtractedTopic(
                topic_id=str(uuid.uuid4()),
                source_messages=[],
                topic_content=content,
                memory_attempts=[],
                fact_constraints=[],
                sing_attempts=[],
                is_forced_from_incomplete=True,
            )

            await chat_stream.topic_replier.add_topic(topic)
            self.logger.info(
                f"Dispatched reminder for '{event.title}' to user {user_id}"
            )
            return True

        except Exception as e:
            self.logger.error(f"Failed to send reminder to {user_id}: {e}")
            return False
