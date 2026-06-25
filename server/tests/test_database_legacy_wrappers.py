import sys
from pathlib import Path
from types import SimpleNamespace

server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

import src.system.database.database_service as database_service


class FakeMemoryStore:
    def __init__(self):
        self.calls = []

    def write_memory_update(self, user_id, memory_update, commit=True):
        self.calls.append(("write_memory_update", user_id, memory_update, commit))

    def write_agent_memory_record(self, memory_record, *, chunk_texts=None, embedding_ids=None, commit=True):
        self.calls.append(("write_agent_memory_record", memory_record, chunk_texts, embedding_ids, commit))
        return "record-id"

    def get_agent_memory_record_by_embedding_id(self, embedding_id):
        self.calls.append(("get_agent_memory_record_by_embedding_id", embedding_id))
        return {"embedding_id": embedding_id}


def test_legacy_write_memory_update_delegates_to_memory_store(monkeypatch):
    store = FakeMemoryStore()
    monkeypatch.setattr(database_service, "_memory_store_for_legacy", lambda db=None, redis=None: store)

    database_service.write_memory_update("db", "redis", "user-id", "update", commit=False)

    assert store.calls == [("write_memory_update", "user-id", "update", False)]


def test_legacy_write_agent_memory_record_delegates_to_memory_store(monkeypatch):
    store = FakeMemoryStore()
    monkeypatch.setattr(database_service, "_memory_store_for_legacy", lambda db=None, redis=None: store)

    result = database_service.write_agent_memory_record(
        "db",
        "record",
        chunk_texts=["chunk"],
        embedding_ids=["embedding"],
        commit=False,
    )

    assert result == "record-id"
    assert store.calls == [
        ("write_agent_memory_record", "record", ["chunk"], ["embedding"], False)
    ]


def test_legacy_get_memory_record_by_embedding_delegates_to_memory_store(monkeypatch):
    store = FakeMemoryStore()
    monkeypatch.setattr(database_service, "_memory_store_for_legacy", lambda db=None, redis=None: store)

    result = database_service.get_agent_memory_record_by_embedding_id("db", "embedding")

    assert result == {"embedding_id": "embedding"}
    assert store.calls == [("get_agent_memory_record_by_embedding_id", "embedding")]


def test_database_manager_can_be_constructed_without_config(monkeypatch):
    monkeypatch.setattr(database_service.DatabaseManager, "init_all_databases", lambda self: None)

    manager = database_service.DatabaseManager()

    assert manager.config == {}
