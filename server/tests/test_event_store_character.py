import asyncio
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.system.database.event_store import EventStore
from src.system.database.sql_database import Event, EventNotification, get_sql_session, init_sql_db


class NoopRedis:
    pass


def test_init_sql_db_migrates_existing_events_table_with_character_column(tmp_path):
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE events (id VARCHAR PRIMARY KEY, event_type VARCHAR NOT NULL, title VARCHAR NOT NULL)"
        )
        conn.commit()
    finally:
        conn.close()

    init_sql_db(str(tmp_path), "legacy.db")
    conn = sqlite3.connect(db_path)
    try:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(events)").fetchall()]
    finally:
        conn.close()

    assert "character" in columns


def test_init_sql_db_migrates_existing_notifications_table_with_character_column(tmp_path):
    db_path = tmp_path / "legacy_notifications.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE event_notifications (id INTEGER PRIMARY KEY AUTOINCREMENT, event_id VARCHAR NOT NULL, user_id VARCHAR NOT NULL, trigger_key VARCHAR NOT NULL)"
        )
        conn.commit()
    finally:
        conn.close()

    init_sql_db(str(tmp_path), "legacy_notifications.db")
    conn = sqlite3.connect(db_path)
    try:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(event_notifications)").fetchall()]
    finally:
        conn.close()

    assert "character_id" in columns


def test_event_store_deduplicates_only_within_same_character(tmp_path):
    init_sql_db(str(tmp_path), "events.db")
    store = EventStore({}, get_sql_session, NoopRedis())
    start = datetime(2026, 7, 1, 20, 0, 0)

    first_id = asyncio.run(
        store.add_event(
            {
                "title": "Concert A",
                "event_type": "concert",
                "start_datetime": start,
                "character": "luotianyi",
                "source": "bilibili",
            }
        )
    )
    second_id = asyncio.run(
        store.add_event(
            {
                "title": "Concert A",
                "event_type": "concert",
                "start_datetime": start,
                "character": "miku",
                "source": "bilibili",
            }
        )
    )
    duplicate_id = asyncio.run(
        store.add_event(
            {
                "title": "Concert A",
                "event_type": "concert",
                "start_datetime": start,
                "character": "miku",
                "source": "bilibili",
            }
        )
    )

    db = get_sql_session()
    try:
        events = db.query(Event).filter(Event.title == "Concert A", Event.is_active == True).all()
        by_character = {event.character: event.id for event in events}
    finally:
        db.close()

    assert first_id is not None
    assert second_id is not None
    assert duplicate_id is None
    assert by_character == {"luotianyi": first_id, "miku": second_id}


def test_event_store_writes_default_character(tmp_path):
    init_sql_db(str(tmp_path), "events.db")
    store = EventStore({}, get_sql_session, NoopRedis())

    event_id = asyncio.run(
        store.add_event(
            {
                "title": "Default Character Event",
                "event_type": "general",
                "start_datetime": datetime(2026, 7, 1, 20, 0, 0),
                "source": "bilibili",
            }
        )
    )

    db = get_sql_session()
    try:
        event = db.query(Event).filter(Event.id == event_id).first()
    finally:
        db.close()

    assert event.character == "luotianyi"


def test_event_store_due_events_are_filtered_by_character(tmp_path):
    init_sql_db(str(tmp_path), "events.db")
    store = EventStore({}, get_sql_session, NoopRedis())
    start = datetime(2026, 7, 1, 20, 0, 0)

    asyncio.run(
        store.add_event(
            {
                "title": "Tianyi Concert",
                "event_type": "concert",
                "start_datetime": start,
                "trigger_conditions": ["day_of_event"],
                "character": "luotianyi",
            }
        )
    )
    asyncio.run(
        store.add_event(
            {
                "title": "Miku Concert",
                "event_type": "concert",
                "start_datetime": start,
                "trigger_conditions": ["day_of_event"],
                "character": "miku",
            }
        )
    )

    tianyi_due = store.get_events_due_for_trigger(character="luotianyi", today=date(2026, 7, 1))
    miku_due = store.get_events_due_for_trigger(character="miku", today=date(2026, 7, 1))

    assert [event["title"] for event, _ in tianyi_due] == ["Tianyi Concert"]
    assert [event["title"] for event, _ in miku_due] == ["Miku Concert"]


def test_event_notification_is_scoped_by_character(tmp_path):
    init_sql_db(str(tmp_path), "events.db")
    store = EventStore({}, get_sql_session, NoopRedis())

    store.mark_notified("event-1", "user-1", "day_of_event", "luotianyi")

    assert store.is_notified("event-1", "user-1", "day_of_event", "luotianyi") is True
    assert store.is_notified("event-1", "user-1", "day_of_event", "miku") is False

    store.mark_notified("event-1", "user-1", "day_of_event", "miku")
    db = get_sql_session()
    try:
        rows = db.query(EventNotification).filter(EventNotification.event_id == "event-1").all()
    finally:
        db.close()

    assert {row.character_id for row in rows} == {"luotianyi", "miku"}
