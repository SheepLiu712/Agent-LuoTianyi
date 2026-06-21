from __future__ import annotations

from typing import Any

from src.world.events import WorldEvent


class ScheduleWorldProvider:
    """World facade over the existing schedule plugin.

    This is deliberately thin. It lets new runtime code depend on `world`
    contracts while the mature schedule implementation remains in place.
    """

    def __init__(self, schedule_manager: Any):
        self.schedule_manager = schedule_manager

    def list_active_events(self, user_id: str | None = None) -> list[WorldEvent]:
        if self.schedule_manager is None:
            return []
        try:
            raw_events = self.schedule_manager.get_events()
        except Exception:
            return []

        result: list[WorldEvent] = []
        for item in raw_events or []:
            if user_id and item.get("is_personal") and item.get("target_user_id") != user_id:
                continue
            result.append(_dict_to_world_event(item))
        return result

    def get_context_for_runtime(self, user_id: str | None = None) -> str:
        if self.schedule_manager is None:
            return ""
        try:
            return self.schedule_manager.get_active_context(user_id or "")
        except Exception:
            return ""


def _dict_to_world_event(item: dict[str, Any]) -> WorldEvent:
    return WorldEvent(
        event_id=str(item.get("id") or ""),
        event_type=str(item.get("event_type") or "general"),
        title=str(item.get("title") or ""),
        description=str(item.get("description") or ""),
        source=str(item.get("source") or ""),
        start_datetime=item.get("start_datetime"),
        end_datetime=item.get("end_datetime"),
        is_personal=bool(item.get("is_personal")),
        target_user_id=item.get("target_user_id"),
        metadata={
            key: value
            for key, value in item.items()
            if key
            not in {
                "id",
                "event_type",
                "title",
                "description",
                "source",
                "start_datetime",
                "end_datetime",
                "is_personal",
                "target_user_id",
            }
        },
    )
