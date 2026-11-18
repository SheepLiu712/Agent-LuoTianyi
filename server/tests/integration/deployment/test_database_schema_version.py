"""Schema upgrades preserve rows, reject unknown versions, and retain SQLite backups."""

import importlib.util
import sqlite3
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parents[3]


@pytest.fixture(params=["main", "songs"])
def database(request, tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(SERVER))
    source = "database/sql_database.py" if request.param == "main" else "song_knowledge.py"
    spec = importlib.util.spec_from_file_location(
        "schema_test_" + request.param, SERVER / "src/infrastructure/persistence" / source
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = tmp_path / "existing.db"

    def initialize():
        if request.param == "main":
            module.init_sql_db(str(tmp_path), path.name)
        else:
            module.init_song_db({"db_folder": str(tmp_path), "db_file": path.name})
        module.engine.dispose()

    return request.param, path, initialize


def test_new_database_is_versioned_and_legacy_rows_survive(database):
    kind, path, initialize = database
    initialize()
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        if kind == "main":
            connection.execute("INSERT INTO users(uuid, username, password) VALUES ('u', 'name', 'hash')")
        else:
            connection.execute(
                "INSERT INTO songs(uuid, name, safe_name, introduction, lyrics) "
                "VALUES ('s', 'song', 'song', 'intro', 'lyrics')"
            )
        connection.execute("PRAGMA user_version=0")
    initialize()
    backups = list(path.parent.glob("existing.db.schema-0-backup-*"))
    assert len(backups) == 1
    table = "users" if kind == "main" else "songs"
    with sqlite3.connect(path) as connection, sqlite3.connect(backups[0]) as backup:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert backup.execute("PRAGMA user_version").fetchone()[0] == 0
        assert (
            connection.execute(f"SELECT * FROM {table}").fetchall()
            == backup.execute(f"SELECT * FROM {table}").fetchall()
        )
    initialize()
    assert list(path.parent.glob("existing.db.schema-0-backup-*")) == backups


def test_newer_database_is_rejected_before_writing(database):
    _, path, initialize = database
    initialize()
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version=2")
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match="Unsupported"):
        initialize()
    assert path.read_bytes() == before
    assert not list(path.parent.glob("*.schema-0-backup-*"))


def test_version_number_does_not_hide_missing_tables(database):
    kind, path, initialize = database
    initialize()
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE " + ("users" if kind == "main" else "songs"))
    with pytest.raises(RuntimeError, match="schema mismatch"):
        initialize()
    with sqlite3.connect(path) as connection:
        assert not connection.execute(
            "SELECT name FROM sqlite_master WHERE name=?", ("users" if kind == "main" else "songs",)
        ).fetchall()


def test_offline_migration_entrypoint(database):
    import subprocess
    import sys

    kind, path, initialize = database
    initialize()
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version=0")
    process = subprocess.run(
        [
            sys.executable,
            str(SERVER / "scripts/deploy/release/migrate_database.py"),
            "--kind",
            kind,
            "--database",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    assert process.returncode == 0, process.stderr
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
    assert len(list(path.parent.glob("*.schema-0-backup-*"))) == 1


def test_failed_legacy_upgrade_keeps_backup_and_does_not_stamp(database):
    kind, path, initialize = database
    initialize()
    table, column = ("users", "username") if kind == "main" else ("songs", "lyrics")
    with sqlite3.connect(path) as connection:
        connection.execute(f"ALTER TABLE {table} RENAME COLUMN {column} TO legacy_column")
        connection.execute("PRAGMA user_version=0")
    with pytest.raises(RuntimeError, match="schema mismatch"):
        initialize()
    backups = list(path.parent.glob("*.schema-0-backup-*"))
    assert len(backups) == 1
    with sqlite3.connect(path) as connection, sqlite3.connect(backups[0]) as backup:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
        assert backup.execute("PRAGMA user_version").fetchone()[0] == 0
        assert "legacy_column" in {row[1] for row in backup.execute(f"PRAGMA table_info({table})")}
