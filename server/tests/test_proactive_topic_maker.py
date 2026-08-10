import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.chat_session.dependency.proactive_topic_maker import (
    ActionActivity,
    ActivityType,
    ProactiveTopicMaker,
)


class FakeEventStore:
    def __init__(self, events=None):
        self.notified = set()
        self.due_calls = []
        self.events = events

    def get_events_due_for_trigger(self, *, character, today=None):
        self.due_calls.append(character)
        if self.events is not None:
            return self.events
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

    def try_claim_notification(self, event_id, user_id, trigger_key, character_id):
        key = (event_id, user_id, trigger_key, character_id)
        if key in self.notified:
            return False
        self.notified.add(key)
        return True

    def release_notification_claim(self, event_id, user_id, trigger_key, character_id):
        key = (event_id, user_id, trigger_key, character_id)
        existed = key in self.notified
        self.notified.discard(key)
        return existed


class FakeTopicReplier:
    def __init__(self, *, fail=False):
        self.topics = []
        self.fail = fail

    async def add_topic(self, topic):
        if self.fail:
            raise RuntimeError("topic queue unavailable")
        self.topics.append(topic)


class BlockingTopicReplier:
    def __init__(self):
        self.topics = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def add_topic(self, topic):
        self.topics.append(topic)
        self.entered.set()
        await self.release.wait()


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
async def test_periodic_checks_randomly_dispatches_only_one_due_event(monkeypatch):
    events = [
        (
            {
                "id": "event-1",
                "event_type": "holiday",
                "title": "节日A",
                "description": "",
                "is_personal": False,
            },
            "day_of_event",
        ),
        (
            {
                "id": "event-2",
                "event_type": "birthday",
                "title": "生日B",
                "description": "",
                "is_personal": True,
                "target_user_id": "idle-user",
            },
            "day_of_event",
        ),
        (
            {
                "id": "event-3",
                "event_type": "new_song",
                "title": "新歌C",
                "description": "",
                "is_personal": False,
            },
            "day_of_event",
        ),
    ]
    monkeypatch.setattr(
        "src.chat_session.dependency.proactive_topic_maker.random.choice",
        lambda candidates: candidates[1],
    )
    maker = ProactiveTopicMaker({"proactive_idle_seconds": 0})
    idle_stream = FakeChatStream("luotianyi", idle=True)
    event_store = FakeEventStore(events)
    maker.configure(
        conversation_service=SimpleNamespace(),
        database_manager=SimpleNamespace(event_store=event_store),
        chat_stream_manager=FakeStreamManager([("idle-user", "luotianyi", idle_stream)]),
    )

    sent = await maker.run_periodic_checks()

    assert sent == 1
    assert len(idle_stream.topic_replier.topics) == 1
    assert "生日B" in idle_stream.topic_replier.topics[0].topic_content
    assert event_store.notified == {("event-2", "idle-user", "day_of_event", "luotianyi")}


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


@pytest.mark.asyncio
async def test_login_does_not_mark_unsupported_event_before_periodic_dispatch():
    event_store = FakeEventStore(
        [
            (
                {
                    "id": "concert-1",
                    "character": "luotianyi",
                    "event_type": "concert",
                    "title": "今晚演唱会",
                    "description": "",
                    "is_personal": False,
                },
                "day_of_event",
            )
        ]
    )
    stream = FakeChatStream("luotianyi", idle=True)
    maker = ProactiveTopicMaker({"proactive_idle_seconds": 0})
    maker.configure(
        conversation_service=SimpleNamespace(),
        database_manager=SimpleNamespace(event_store=event_store),
        chat_stream_manager=FakeStreamManager([("alice", "luotianyi", stream)]),
    )

    await maker.dispatch_action(
        ActionActivity(ActivityType.REGULAR_LOGIN),
        "alice",
        stream,
    )

    assert stream.topic_replier.topics == []
    assert event_store.notified == set()

    sent = await maker.run_periodic_checks()

    assert sent == 1
    assert len(stream.topic_replier.topics) == 1
    assert event_store.notified == {
        ("concert-1", "alice", "day_of_event", "luotianyi")
    }


@pytest.mark.asyncio
async def test_login_build_failure_does_not_mark_event(monkeypatch):
    event_store = FakeEventStore(
        [
            (
                {
                    "id": "holiday-1",
                    "character": "luotianyi",
                    "event_type": "holiday",
                    "title": "测试节日",
                    "is_personal": False,
                },
                "day_of_event",
            )
        ]
    )
    stream = FakeChatStream("luotianyi", idle=True)
    maker = ProactiveTopicMaker({"proactive_idle_seconds": 0})
    maker.configure(
        conversation_service=SimpleNamespace(),
        database_manager=SimpleNamespace(event_store=event_store),
        chat_stream_manager=FakeStreamManager([]),
    )

    def fail_build(event_dict):
        raise ValueError("invalid event payload")

    monkeypatch.setattr(maker, "_build_login_reminder_topic", fail_build)

    await maker.dispatch_action(
        ActionActivity(ActivityType.REGULAR_LOGIN),
        "alice",
        stream,
    )

    assert stream.topic_replier.topics == []
    assert event_store.notified == set()


@pytest.mark.asyncio
@pytest.mark.parametrize("dispatch_path", ["login", "periodic"])
async def test_enqueue_failure_does_not_mark_event(dispatch_path):
    event_store = FakeEventStore(
        [
            (
                {
                    "id": "holiday-1",
                    "character": "luotianyi",
                    "event_type": "holiday",
                    "title": "测试节日",
                    "is_personal": False,
                },
                "day_of_event",
            )
        ]
    )
    stream = FakeChatStream("luotianyi", idle=True)
    stream.topic_replier = FakeTopicReplier(fail=True)
    maker = ProactiveTopicMaker({"proactive_idle_seconds": 0})
    maker.configure(
        conversation_service=SimpleNamespace(),
        database_manager=SimpleNamespace(event_store=event_store),
        chat_stream_manager=FakeStreamManager([("alice", "luotianyi", stream)]),
    )

    if dispatch_path == "login":
        with pytest.raises(RuntimeError, match="topic queue unavailable"):
            await maker.dispatch_action(
                ActionActivity(ActivityType.REGULAR_LOGIN),
                "alice",
                stream,
            )
    else:
        assert await maker.run_periodic_checks() == 0

    assert event_store.notified == set()


@pytest.mark.asyncio
@pytest.mark.parametrize("dispatch_path", ["login", "periodic"])
async def test_reminders_filter_user_and_character_before_dispatch(dispatch_path):
    events = [
        (
            {
                "id": "bob-private",
                "character": "luotianyi",
                "event_type": "new_song",
                "title": "Bob的私人事件",
                "is_personal": True,
                "target_user_id": "bob",
            },
            "day_of_event",
        ),
        (
            {
                "id": "wrong-character",
                "character": "miku",
                "event_type": "new_song",
                "title": "其他角色事件",
                "is_personal": True,
                "target_user_id": "alice",
            },
            "day_of_event",
        ),
        (
            {
                "id": "alice-private",
                "character": "luotianyi",
                "event_type": "new_song",
                "title": "Alice的事件",
                "is_personal": True,
                "target_user_id": "alice",
            },
            "day_of_event",
        ),
    ]
    event_store = FakeEventStore(events)
    stream = FakeChatStream("luotianyi", idle=True)
    maker = ProactiveTopicMaker({"proactive_idle_seconds": 0})
    maker.configure(
        conversation_service=SimpleNamespace(),
        database_manager=SimpleNamespace(event_store=event_store),
        chat_stream_manager=FakeStreamManager([("alice", "luotianyi", stream)]),
    )

    if dispatch_path == "login":
        await maker.dispatch_action(
            ActionActivity(ActivityType.REGULAR_LOGIN),
            "alice",
            stream,
        )
    else:
        assert await maker.run_periodic_checks() == 1

    assert len(stream.topic_replier.topics) == 1
    content = stream.topic_replier.topics[0].topic_content
    assert "Alice的事件" in content
    assert "Bob的私人事件" not in content
    assert "其他角色事件" not in content
    assert event_store.notified == {
        ("alice-private", "alice", "day_of_event", "luotianyi")
    }


@pytest.mark.asyncio
async def test_login_and_periodic_dispatch_share_one_inflight_claim():
    events = [
        (
            {
                "id": "holiday-claim",
                "character": "luotianyi",
                "event_type": "holiday",
                "title": "测试节日",
                "description": "",
                "is_personal": False,
            },
            "day_of_event",
        )
    ]
    event_store = FakeEventStore(events)
    stream = FakeChatStream("luotianyi", idle=True)
    stream.topic_replier = BlockingTopicReplier()
    maker = ProactiveTopicMaker({"proactive_idle_seconds": 0})
    maker.configure(
        conversation_service=SimpleNamespace(),
        database_manager=SimpleNamespace(event_store=event_store),
        chat_stream_manager=FakeStreamManager([("alice", "luotianyi", stream)]),
    )

    login = asyncio.create_task(
        maker.dispatch_action(
            ActionActivity(ActivityType.REGULAR_LOGIN),
            "alice",
            stream,
        )
    )
    await asyncio.wait_for(stream.topic_replier.entered.wait(), timeout=0.5)

    assert await maker.run_periodic_checks() == 0

    stream.topic_replier.release.set()
    await asyncio.wait_for(login, timeout=0.5)
    assert len(stream.topic_replier.topics) == 1
    assert event_store.notified == {
        ("holiday-claim", "alice", "day_of_event", "luotianyi")
    }
