"""Durable database and due-event adapters belong to infrastructure."""

from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[3]


def test_database_package_is_owned_by_infrastructure_persistence() -> None:
    database = SERVER_ROOT / "src" / "infrastructure" / "persistence" / "database"

    assert (database / "database_service.py").is_file()
    assert (database / "sql_database.py").is_file()
    assert (database / "vector_store.py").is_file()
    assert (database / "services" / "event_store.py").is_file()
    assert not (SERVER_ROOT / "src" / "system" / "database").exists()


def test_due_event_provider_is_a_persistence_adapter() -> None:
    assert (SERVER_ROOT / "src" / "infrastructure" / "persistence" / "due_events.py").is_file()
    assert not (SERVER_ROOT / "src" / "system" / "due_event_provider.py").exists()
