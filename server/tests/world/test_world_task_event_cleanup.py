from types import SimpleNamespace


from src.world.event_cleanup_task import ExpiredEventCleanupTask


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
