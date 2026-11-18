"""SQLite schema contract shared by startup and read-only deployment checks."""

import json
import os
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path

CONTRACT_PATH = Path(__file__).with_name("database_schema.json")


def contract():
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def snapshot(connection):
    tables = {}
    for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
        quoted = '"' + name.replace('"', '""') + '"'
        tables[name] = {row[1]: row[2].upper() for row in connection.execute(f"PRAGMA table_info({quoted})")}
    return tables


def validate(connection, expected):
    actual = snapshot(connection)
    errors = []
    for table, columns in expected.items():
        for column, kind in columns.items():
            if actual.get(table, {}).get(column) != kind:
                errors.append(f"schema mismatch: {table}.{column}")
    if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
        errors.append("SQLite integrity check failed")
    return errors


def inspect_database(path, requirement):
    """mode=ro never creates a missing database; no business content in the result."""
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        errors = validate(connection, requirement["tables"]) if version == requirement["version"] else []
        if version == 0 and not set(snapshot(connection)) & set(requirement["tables"]):
            errors.append("Unversioned database has no recognized tables")
        return version, errors


def guard_version(path, kind):
    """Reject newer schemas before create_all or legacy migrations can write."""
    if not Path(path).exists():
        return 0
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        expected = contract()["databases"][kind]
        if version not in (0, expected["version"]):
            raise RuntimeError(f"Unsupported {kind} database schema {version}")
        if version == expected["version"]:
            errors = validate(connection, expected["tables"])
            if errors:
                raise RuntimeError("; ".join(errors))
        if version == 0:
            tables = snapshot(connection)
            if tables and not set(tables) & set(expected["tables"]):
                raise RuntimeError("Unrecognized legacy database; refusing migration")
            backup = Path(str(path) + ".schema-0-backup-" + uuid.uuid4().hex)
            backup.touch(mode=0o600, exist_ok=False)
            os.chmod(backup, 0o600)
            with closing(sqlite3.connect(backup)) as destination:
                connection.backup(destination)
                destination.execute("PRAGMA journal_mode=DELETE")
                if destination.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise RuntimeError("Database backup validation failed")
        return version


def stamp(connection, kind):
    expected = contract()["databases"][kind]
    errors = validate(connection, expected["tables"])
    if errors:
        raise RuntimeError("; ".join(errors))
    connection.execute(f"PRAGMA user_version={expected['version']}")
