from datetime import date, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.system.database.redis_buffer import RedisBuffer
from src.system.database.services.event_store import EventStore
from src.system.database.sql_database import Base, Event
from src.world.event_cleanup_task import ExpiredEventCleanupTask


TODAY = date(2026, 9, 14)


class FakeEventStore:
    def __init__(self, purged=0):
        self.purged = purged
        self.calls = 0

    def purge_expired_events(self):
        self.calls += 1
        return self.purged


def test_expired_event_cleanup_initialize_reads_event_store():
    event_store = FakeEventStore()
    runtime = SimpleNamespace(database_manager=SimpleNamespace(event_store=event_store))
    task = ExpiredEventCleanupTask()

    task.initialize(runtime)

    assert task.event_store is event_store


def test_expired_event_cleanup_skips_without_store():
    task = ExpiredEventCleanupTask()

    result = task.run_once()

    assert result.ok is True
    assert result.skipped is True


def test_expired_event_cleanup_purges_events():
    event_store = FakeEventStore(purged=4)
    task = ExpiredEventCleanupTask()
    task.event_store = event_store

    result = task.run_once()

    assert result.ok is True
    assert result.data["purged"] == 4
    assert event_store.calls == 1


@pytest.fixture
def store(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'events.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    yield EventStore({}, sessions, RedisBuffer()), sessions
    engine.dispose()


def _add(sessions, **fields):
    fields.setdefault("event_type", "general")
    fields.setdefault("title", fields.get("id", "event"))
    with sessions() as session:
        session.add(Event(**fields))
        session.commit()


def _is_active(sessions, event_id):
    with sessions() as session:
        return session.query(Event).filter(Event.id == event_id).first().is_active


def test_purge_deactivates_end_before_today_and_keeps_end_today(store):
    event_store, sessions = store
    _add(sessions, id="past", end_datetime=datetime(2026, 9, 13, 12, 0))
    _add(sessions, id="today", end_datetime=datetime(2026, 9, 14, 12, 0))
    assert event_store.purge_expired_events(today=TODAY) == 1
    assert _is_active(sessions, "past") is False
    assert _is_active(sessions, "today") is True


def test_purge_gives_start_only_events_one_day_buffer(store):
    event_store, sessions = store
    _add(sessions, id="old", start_datetime=datetime(2026, 9, 12, 12, 0))
    _add(sessions, id="yesterday", start_datetime=datetime(2026, 9, 13, 12, 0))
    _add(sessions, id="today", start_datetime=datetime(2026, 9, 14, 8, 0))
    assert event_store.purge_expired_events(today=TODAY) == 1
    assert _is_active(sessions, "old") is False
    assert _is_active(sessions, "yesterday") is True
    assert _is_active(sessions, "today") is True


def test_purge_preserves_recurring_user_and_mmdd_events(store):
    event_store, sessions = store
    _add(sessions, id="recurring", is_recurring=True, end_datetime=datetime(2020, 1, 1))
    _add(sessions, id="user", source="user", end_datetime=datetime(2020, 1, 1))
    _add(sessions, id="mmdd", date_mmdd="01-01")
    assert event_store.purge_expired_events(today=TODAY) == 0
    assert _is_active(sessions, "recurring") is True
    assert _is_active(sessions, "user") is True
    assert _is_active(sessions, "mmdd") is True


def test_purge_is_idempotent_and_soft_deletes(store):
    event_store, sessions = store
    _add(sessions, id="past", end_datetime=datetime(2026, 9, 1))
    assert event_store.purge_expired_events(today=TODAY) == 1
    assert event_store.purge_expired_events(today=TODAY) == 0
    assert _is_active(sessions, "past") is False


def test_purge_ignores_already_inactive_events(store):
    event_store, sessions = store
    _add(sessions, id="inactive", is_active=False, end_datetime=datetime(2026, 9, 1))
    assert event_store.purge_expired_events(today=TODAY) == 0


def test_purge_invalidates_due_cache(store):
    event_store, sessions = store
    event_store._due_events_cache[(TODAY, "character")] = []
    _add(sessions, id="past", end_datetime=datetime(2026, 9, 1))
    assert event_store.purge_expired_events(today=TODAY) == 1
    assert event_store._due_events_cache == {}
