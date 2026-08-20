import json
import sys
import threading
from datetime import date, datetime, time
from pathlib import Path
from types import SimpleNamespace


server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.system.database.services.event_store import EventStore


class NoopRedis:
    pass


class SnapshotSource:
    def __init__(self, rows):
        self.rows = rows
        self.snapshot_captured = threading.Event()
        self.release_snapshot = threading.Event()


class SnapshotQuery:
    def __init__(self, source, block):
        self.source = source
        self.block = block

    def filter(self, *args):
        return self

    def all(self):
        snapshot = list(self.source.rows)
        if self.block:
            self.source.snapshot_captured.set()
            if not self.source.release_snapshot.wait(timeout=2):
                raise TimeoutError("test did not release the stale event snapshot")
        return snapshot


class SnapshotSession:
    def __init__(self, source, block):
        self.source = source
        self.block = block

    def query(self, *args):
        return SnapshotQuery(self.source, self.block)

    def close(self):
        pass


class SnapshotSessionFactory:
    def __init__(self, source):
        self.source = source
        self.calls = 0
        self._lock = threading.Lock()

    def __call__(self):
        with self._lock:
            self.calls += 1
            block = self.calls == 1
        return SnapshotSession(self.source, block)


def make_event_row(event_id, title):
    now = datetime.now()
    return SimpleNamespace(
        id=event_id,
        character="luotianyi",
        event_type="general",
        title=title,
        description="",
        date_type="solar",
        date_mmdd="",
        start_datetime=datetime.combine(date.today(), time(hour=12)),
        end_datetime=None,
        duration_minutes=None,
        trigger_conditions=json.dumps(["day_of_event"]),
        is_recurring=False,
        is_personal=False,
        target_user_id=None,
        source="test",
        source_url="",
        source_platform="",
        is_active=True,
        created_at=now,
        updated_at=now,
    )


def run_stale_read(read):
    result = []
    errors = []

    def target():
        try:
            result.append(read())
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=target)
    thread.start()
    return thread, result, errors


def finish_thread(thread, errors):
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert errors == []


def test_stale_all_events_read_does_not_repopulate_invalidated_cache():
    old_row = make_event_row("old", "Old snapshot")
    new_row = make_event_row("new", "Committed event")
    source = SnapshotSource([old_row])
    sessions = SnapshotSessionFactory(source)
    store = EventStore({}, sessions, NoopRedis())

    thread, stale_result, errors = run_stale_read(store.get_all_events)
    assert source.snapshot_captured.wait(timeout=2)

    source.rows = [new_row]
    store._invalidate_cache()
    source.release_snapshot.set()
    finish_thread(thread, errors)

    assert [event["id"] for event in stale_result[0]] == ["old"]
    assert store._all_events_cache is None
    assert [event["id"] for event in store.get_all_events()] == ["new"]
    assert sessions.calls == 2


def test_stale_due_events_read_does_not_repopulate_invalidated_cache():
    new_row = make_event_row("new", "Due after write")
    source = SnapshotSource([])
    sessions = SnapshotSessionFactory(source)
    store = EventStore({}, sessions, NoopRedis())
    cache_key = (date.today(), "luotianyi")

    thread, stale_result, errors = run_stale_read(
        lambda: store.get_events_due_for_trigger(
            character="luotianyi",
            today=date.today(),
        )
    )
    assert source.snapshot_captured.wait(timeout=2)

    source.rows = [new_row]
    store._invalidate_cache()
    source.release_snapshot.set()
    finish_thread(thread, errors)

    assert stale_result == [[]]
    assert cache_key not in store._due_events_cache
    fresh = store.get_events_due_for_trigger(
        character="luotianyi",
        today=date.today(),
    )
    assert [(event["id"], trigger) for event, trigger in fresh] == [
        ("new", "day_of_event")
    ]
    assert sessions.calls == 2
