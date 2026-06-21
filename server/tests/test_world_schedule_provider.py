import os
import sys
from datetime import datetime

current_dir = os.getcwd()
if current_dir not in sys.path:
    sys.path.append(current_dir)

from src.world.schedule_provider import ScheduleWorldProvider


class FakeScheduleManager:
    def get_events(self):
        return [
            {
                "id": "public-1",
                "event_type": "concert",
                "title": "演唱会",
                "description": "今晚有演唱会",
                "source": "bilibili",
                "start_datetime": datetime(2026, 6, 20, 20, 0, 0),
                "is_personal": False,
            },
            {
                "id": "private-1",
                "event_type": "birthday",
                "title": "用户生日",
                "description": "只对 user-2 有意义",
                "source": "user",
                "is_personal": True,
                "target_user_id": "user-2",
            },
        ]

    def get_active_context(self, user_id):
        return f"context for {user_id}"


def test_schedule_world_provider_maps_legacy_events():
    provider = ScheduleWorldProvider(FakeScheduleManager())

    events = provider.list_active_events(user_id="user-1")
    assert len(events) == 1
    assert events[0].event_id == "public-1"
    assert events[0].event_type == "concert"
    assert events[0].title == "演唱会"


def test_schedule_world_provider_delegates_context():
    provider = ScheduleWorldProvider(FakeScheduleManager())

    assert provider.get_context_for_runtime("user-1") == "context for user-1"
