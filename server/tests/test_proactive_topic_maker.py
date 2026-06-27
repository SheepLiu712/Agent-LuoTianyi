import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.chat_session.dependency.proactive_topic_maker import ProactiveTopicMaker


class FakeEventStore:
    def __init__(self):
        self.notified = set()
        self.due_calls = []

    def get_events_due_for_trigger(self, *, character, today=None):
        self.due_calls.append(character)
        return [
            (
                {
                    "id": f"{character}-event",
                    "event_type": "concert",
                    "title": f"{character}演唱会",
                    "description": "今晚有活动",
                    "is_personal": False,
                },
                "day_of_event",
            )
        ]

    def is_notified(self, event_id, user_id, trigger_key, character_id):
        return (event_id, user_id, trigger_key, character_id) in self.notified

    def mark_notified(self, event_id, user_id, trigger_key, character_id):
        self.notified.add((event_id, user_id, trigger_key, character_id))


class FakeTopicReplier:
    def __init__(self):
        self.topics = []

    async def add_topic(self, topic):
        self.topics.append(topic)


class FakeChatStream:
    def __init__(self, character_id, *, idle):
        self.character_id = character_id
        self.idle = idle
        self.proactive_idle_checks = 0
        self.topic_replier = FakeTopicReplier()

    def is_connection_lost(self):
        return False

    def can_dispatch_proactive(self, min_idle_seconds):
        self.proactive_idle_checks += 1
        return self.idle

class FakeStreamManager:
    def __init__(self, streams):
        self.streams = streams

    def iter_active_streams(self):
        yield from self.streams


@pytest.mark.asyncio
async def test_periodic_checks_dispatch_only_when_stream_is_idle():
    maker = ProactiveTopicMaker({"proactive_idle_seconds": 30})
    busy_stream = FakeChatStream("luotianyi", idle=False)
    idle_stream = FakeChatStream("miku", idle=True)
    event_store = FakeEventStore()
    maker.configure(
        conversation_service=SimpleNamespace(),
        database_manager=SimpleNamespace(event_store=event_store),
        chat_stream_manager=FakeStreamManager(
            [
                ("busy-user", "luotianyi", busy_stream),
                ("idle-user", "miku", idle_stream),
            ]
        ),
    )

    sent = await maker.run_periodic_checks()

    assert sent == 1
    assert busy_stream.topic_replier.topics == []
    assert len(idle_stream.topic_replier.topics) == 1
    assert event_store.due_calls == ["miku"]
    assert event_store.notified == {("miku-event", "idle-user", "day_of_event", "miku")}


@pytest.mark.asyncio
async def test_login_activity_is_released_after_chat_stream_ready():
    maker = ProactiveTopicMaker({"return_user_threshold_seconds": 10, "proactive_idle_seconds": 0})
    stream = FakeChatStream("luotianyi", idle=False)

    await maker.on_user_login("user-1", 11)
    assert maker.pending_login_times == {"user-1": 11}

    await maker.on_user_login("user-1", chat_stream=stream)

    assert maker.pending_login_times == {}
    assert stream.proactive_idle_checks == 0
    assert len(stream.topic_replier.topics) == 1
    assert "用户已1天未登录" in stream.topic_replier.topics[0].topic_content
