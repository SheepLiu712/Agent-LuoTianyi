import json
import sys
from datetime import date
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
from src.subconscious.date_processor import DateDetector, process_detected_date
from src.system.database.services.event_store import EventStore
from src.system.database.sql_database import Event, get_sql_session, init_sql_db


class NoopRedis:
    pass


class FakeLLMModule:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def generate_response(self, **kwargs):
        self.calls.append(kwargs)
        return json.dumps(self.payload, ensure_ascii=False)


class FakeTopicReplier:
    def __init__(self):
        self.topics = []

    async def add_topic(self, topic):
        self.topics.append(topic)


class FakeChatStream:
    def __init__(self, character_id="luotianyi", *, idle=True):
        self.character_id = character_id
        self.idle = idle
        self.topic_replier = FakeTopicReplier()

    def can_dispatch_proactive(self, min_idle_seconds):
        return self.idle


class FakeStreamManager:
    def __init__(self, streams):
        self.streams = streams

    def iter_active_streams(self):
        yield from self.streams


def _today_mmdd() -> str:
    today = date.today()
    return f"{today.month:02d}-{today.day:02d}"


def _make_event_store(tmp_path) -> EventStore:
    init_sql_db(str(tmp_path), "events.db")
    return EventStore({}, get_sql_session, NoopRedis())


async def _write_birthday(store: EventStore, user_id: str = "user-1", title: str = "用户生日") -> bool:
    return await process_detected_date(
        date_info={
            "name": title,
            "type": "生日",
            "date": _today_mmdd(),
            "description": "用户自己的生日",
            "confidence": 0.99,
        },
        user_id=user_id,
        open_sql_session=get_sql_session,
        reply_topic_callback=None,
        event_store=store,
        character_id="luotianyi",
    )


def _make_maker(store: EventStore, stream: FakeChatStream, user_id: str = "user-1") -> ProactiveTopicMaker:
    maker = ProactiveTopicMaker({"proactive_idle_seconds": 0})
    maker.configure(
        conversation_service=SimpleNamespace(),
        database_manager=SimpleNamespace(event_store=store),
        chat_stream_manager=FakeStreamManager([(user_id, stream.character_id, stream)]),
    )
    return maker


@pytest.mark.asyncio
async def test_date_detector_detects_birthday_from_user_text():
    llm = FakeLLMModule(
        {
            "has_date": True,
            "name": "用户生日",
            "type": "生日",
            "date": "07-09",
            "description": "用户说今天是自己的生日",
            "confidence": 0.98,
        }
    )
    detector = DateDetector({}, "luotianyi", llm)

    no_call = await detector.detect("今天只是普通聊天")
    detected = await detector.detect("今天是我的生日")

    assert no_call is None
    assert detected["type"] == "生日"
    assert detected["date"] == "07-09"
    assert detected["confidence"] == 0.98
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_birthday_write_is_due_today_and_refreshes_event_cache(tmp_path):
    store = _make_event_store(tmp_path)
    assert store.get_events_due_for_trigger(character="luotianyi", today=date.today()) == []

    saved = await _write_birthday(store)

    assert saved is True
    due = store.get_events_due_for_trigger(character="luotianyi", today=date.today())
    assert len(due) == 1
    event, trigger_key = due[0]
    assert trigger_key == "day_of_event"
    assert event["event_type"] == "birthday"
    assert event["title"] == "用户生日"
    assert event["target_user_id"] == "user-1"

    db = get_sql_session()
    try:
        row = db.query(Event).filter(Event.id == event["id"]).first()
        assert row.user_id == "user-1"
        assert row.target_user_id == "user-1"
        assert row.character == "luotianyi"
        assert row.date_mmdd == _today_mmdd()
        assert row.is_recurring is True
        assert row.is_personal is True
    finally:
        db.close()


@pytest.mark.asyncio
async def test_birthday_write_updates_existing_event_without_duplicate(tmp_path):
    store = _make_event_store(tmp_path)

    first_saved = await _write_birthday(store, title="用户生日")
    second_saved = await process_detected_date(
        date_info={
            "name": "用户生日",
            "type": "生日",
            "date": _today_mmdd(),
            "description": "用户后来补充的生日描述",
            "confidence": 0.99,
        },
        user_id="user-1",
        open_sql_session=get_sql_session,
        reply_topic_callback=None,
        event_store=store,
        character_id="luotianyi",
    )

    db = get_sql_session()
    try:
        rows = (
            db.query(Event)
            .filter(
                Event.event_type == "birthday",
                Event.title == "用户生日",
                Event.target_user_id == "user-1",
                Event.is_active == True,
            )
            .all()
        )
    finally:
        db.close()

    assert first_saved is True
    assert second_saved is True
    assert len(rows) == 1
    assert rows[0].description == "用户后来补充的生日描述"


@pytest.mark.asyncio
async def test_login_birthday_reminder_marks_notified_so_world_task_does_not_repeat(tmp_path):
    store = _make_event_store(tmp_path)
    await _write_birthday(store)
    stream = FakeChatStream(idle=True)
    maker = _make_maker(store, stream)

    await maker.dispatch_action(ActionActivity(ActivityType.REGULAR_LOGIN), "user-1", stream)
    sent_by_world = await maker.run_periodic_checks()

    assert len(stream.topic_replier.topics) == 1
    assert "用户生日" in stream.topic_replier.topics[0].topic_content
    assert sent_by_world == 0
    assert len(stream.topic_replier.topics) == 1


@pytest.mark.asyncio
async def test_world_birthday_reminder_marks_notified_so_login_does_not_repeat(tmp_path):
    store = _make_event_store(tmp_path)
    await _write_birthday(store)
    stream = FakeChatStream(idle=True)
    maker = _make_maker(store, stream)

    sent_by_world = await maker.run_periodic_checks()
    await maker.dispatch_action(ActionActivity(ActivityType.REGULAR_LOGIN), "user-1", stream)

    assert sent_by_world == 1
    assert len(stream.topic_replier.topics) == 1
    assert "用户生日" in stream.topic_replier.topics[0].topic_content
