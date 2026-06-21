"""
提醒派发器（独立模块，也可由 ScheduleManager 调用）。

职责：
- 检查今天需要触发的所有事件
- 对每个事件，根据触发条件向在线用户推送提醒
- 通过 EventStore 维护通知记录，避免重复发送
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from src.utils.logger import get_logger
from src.utils.lunar_date import get_holiday_name
from src.plugins.schedule.event_models import (
    UnifiedEventType,
    get_event_type_cn,
    parse_trigger_conditions,
    check_trigger_condition,
    db_event_to_dict,
)
from src.plugins.schedule.event_store import EventStore
from src.plugins.schedule.activity_context_provider import ActivityContextProvider

if TYPE_CHECKING:
    from src.system.chat_session.global_chat_stream_manager import GlobalChatStreamManager

logger = get_logger(__name__)


class ReminderDispatcher:
    """将到期事件提醒推送给在线用户。"""

    def __init__(
        self,
        event_store: EventStore,
        context_provider: ActivityContextProvider,
    ):
        self.event_store = event_store
        self.context_provider = context_provider
        self.gcsm: Optional["GlobalChatStreamManager"] = None
        self.logger = get_logger(__name__)

    # ── 主入口 ────────────────────────────────────────

    async def dispatch_all_due(self) -> int:
        """
        检查今天需要触发的所有事件，向符合条件的在线用户发送提醒。
        返回本次派发的提醒总数。
        """
        today = datetime.now().date()
        due_events = self.event_store.get_events_due_for_trigger(today=today)
        total = 0

        for event_dict, trigger_key in due_events:
            n = await self._dispatch_one_event(event_dict, trigger_key)
            total += n

        if total:
            self.logger.info(f"Dispatched {total} reminder(s) in total")
        return total

    # ── 内部方法 ──────────────────────────────────────

    async def _dispatch_one_event(self, event_dict: Dict[str, Any], trigger_key: str) -> int:
        """对单个事件-触发条件对，向符合条件的用户发送提醒。"""
        event_id = event_dict["id"]
        is_personal = event_dict.get("is_personal", False)
        target_user_id = event_dict.get("target_user_id")

        if is_personal and target_user_id:
            # 个人事件：只发给目标用户
            online_users = [target_user_id] if target_user_id in self._get_online_user_ids() else []
        else:
            # 公开事件：发给所有在线用户
            online_users = self._get_online_user_ids()

        sent = 0
        for user_id in online_users:
            if self.event_store.is_notified(event_id, user_id, trigger_key):
                continue
            ok = await self._send_reminder_to_user(event_dict, trigger_key, user_id)
            if ok:
                self.event_store.mark_notified(event_id, user_id, trigger_key)
                sent += 1

        return sent

    def _get_online_user_ids(self) -> List[str]:
        """从 GCSM 获取在线用户的 user_id 列表。"""
        try:
            gcsm = self._get_gcsm()
            if gcsm is None:
                return []
            return [
                uid
                for uid, stream in gcsm.user_streams.items()
                if stream and not stream.is_connection_lost()
            ]
        except Exception as e:
            self.logger.warning(f"Failed to get online users: {e}")
            return []

    def _get_gcsm(self) -> Optional["GlobalChatStreamManager"]:
        if self.gcsm is None:
            return None
        try:
            return self.gcsm
        except Exception:
            return None

    async def _send_reminder_to_user(
        self, event_dict: Dict[str, Any], trigger_key: str, user_id: str
    ) -> bool:
        """向单个用户发送提醒（通过 ChatStream 的 topic_replier）。"""
        try:
            gcsm = self._get_gcsm()
            if gcsm is None:
                return False
            chat_stream = gcsm.user_streams.get(user_id)
            if chat_stream is None or chat_stream.is_connection_lost():
                return False

            event_type = event_dict.get("event_type", UnifiedEventType.GENERAL.value)
            title = event_dict.get("title", "")
            description = event_dict.get("description", "")
            type_name_cn = get_event_type_cn(UnifiedEventType(event_type))

            # 根据触发条件生成时间描述
            trigger_desc_map = {
                "7_days_before": "一周后",
                "3_days_before": "三天后",
                "1_day_before": "明天",
                "day_of_event": "今天",
                "1_day_after": "昨天",
                "1_hour_before": "一小时后",
            }
            time_desc = trigger_desc_map.get(trigger_key, "即将到来的")

            content = f"{time_desc}有{type_name_cn}「{title}」"
            if description:
                content += f"，{description}"
            content += "。聊聊心情，或问用户是否感兴趣。"

            from src.agent.chat.topic_planner import ExtractedTopic
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
                f"Dispatched reminder for '{title}' (trigger={trigger_key}) to user {user_id}"
            )
            return True

        except Exception as e:
            self.logger.error(f"Failed to send reminder to {user_id}: {e}")
            return False
