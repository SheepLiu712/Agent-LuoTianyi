"""把 EventStore 适配为 角色的话题事件端口。"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from src.domain.agent.due_events import DueEvent


class EventStoreDueEventProvider:
    """转换 EventStore 快照，并复用通知记录保存话题分享结果。"""

    def __init__(self, event_store) -> None:
        if event_store is None:
            raise RuntimeError("角色主动话题缺少事件存储")
        self._event_store = event_store

    def list_due(
        self,
        *,
        character_id: str,
        user_id: str,
        now: datetime,
    ) -> tuple[DueEvent, ...]:
        values = []
        for event, trigger_key in self._event_store.get_events_due_for_trigger(
            character=character_id,
            today=now.astimezone(ZoneInfo("Asia/Shanghai")).date(),
        ):
            event_id = event.get("id")
            if not isinstance(event_id, str) or not event_id.strip():
                continue
            due_at = event.get("start_datetime")
            if not isinstance(due_at, datetime):
                due_at = now
            elif due_at.tzinfo is None:
                due_at = due_at.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
            target_user_id = event.get("target_user_id")
            values.append(
                DueEvent(
                    event_id=event_id,
                    title=event["title"],
                    description=event.get("description") or "",
                    trigger_key=str(trigger_key),
                    reason=str(event.get("event_type") or "event"),
                    due_at=due_at,
                    character_id=str(event.get("character") or character_id),
                    is_personal=bool(event.get("is_personal", False)),
                    target_user_id=(str(target_user_id) if target_user_id is not None else None),
                    is_notified=self._event_store.is_notified(
                        event_id,
                        user_id,
                        str(trigger_key),
                        character_id,
                    ),
                )
            )
        return tuple(values)

    def claim(
        self,
        event_id: str,
        *,
        user_id: str,
        character_id: str,
        trigger_key: str,
    ) -> bool:
        return self._event_store.try_claim_notification(
            event_id,
            user_id,
            trigger_key,
            character_id,
        )
