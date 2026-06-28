import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from migrate_production_data import (
    DEFAULT_LOCAL_DATA,
    DEFAULT_PROD_DATA,
    MISSING_VALUE_FALLBACKS,
    MIGRATED_TABLES,
    PRESERVED_TABLES,
    PRODUCTION_DIRS,
    SQL_DB_RELATIVE,
    _connect,
    _create_sqlite_snapshot,
    _directory_fingerprints,
    _fallback_for_missing_value,
    _quote_identifier,
    _table_columns,
)


def _serialize_row(values: list[Any]) -> bytes:
    return json.dumps(values, ensure_ascii=False, default=str, separators=(",", ":")).encode("utf-8")


def _hash_serialized_rows(rows: list[bytes]) -> str:
    digest = hashlib.sha256()
    for row in sorted(rows):
        digest.update(row)
        digest.update(b"\n")
    return digest.hexdigest()


def _target_table_fingerprint(conn: sqlite3.Connection, table: str, columns: list[str]) -> str:
    select_sql = (
        f"SELECT {', '.join(_quote_identifier(name) for name in columns)} "
        f"FROM {_quote_identifier(table)}"
    )
    rows = [_serialize_row(list(row)) for row in conn.execute(select_sql)]
    return _hash_serialized_rows(rows)


def _projected_production_fingerprint(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    table: str,
) -> str:
    source_columns = {row["name"] for row in _table_columns(source, table)}
    target_columns = _table_columns(target, table)
    source_select_columns = [row["name"] for row in target_columns if row["name"] in source_columns]
    select_sql = (
        f"SELECT {', '.join(_quote_identifier(name) for name in source_select_columns)} "
        f"FROM {_quote_identifier(table)}"
    )

    rows = []
    for row in source.execute(select_sql):
        values = []
        for column in target_columns:
            name = column["name"]
            if name in source_columns:
                values.append(row[name])
            else:
                values.append(_fallback_for_missing_value(table, column))
        rows.append(_serialize_row(values))
    return _hash_serialized_rows(rows)


def _compare_migrated_tables(prod_db: Path, local_db: Path) -> None:
    source = _connect(prod_db)
    target = _connect(local_db)
    try:
        for table in MIGRATED_TABLES:
            columns = [row["name"] for row in _table_columns(target, table)]
            expected = _projected_production_fingerprint(source, target, table)
            actual = _target_table_fingerprint(target, table, columns)
            count = target.execute(f"SELECT COUNT(*) FROM {_quote_identifier(table)}").fetchone()[0]
            print(f"migrated {table}: rows={count} hash={actual}")
            if expected != actual:
                raise RuntimeError(f"Migrated table content differs: {table}")
    finally:
        source.close()
        target.close()


def _compare_preserved_tables(backup_db: Path, local_db: Path) -> None:
    backup = _connect(backup_db)
    target = _connect(local_db)
    try:
        for table in PRESERVED_TABLES:
            backup_columns = [row["name"] for row in _table_columns(backup, table)]
            target_columns = [row["name"] for row in _table_columns(target, table)]
            if backup_columns != target_columns:
                raise RuntimeError(f"Preserved table schema differs: {table}")
            expected = _target_table_fingerprint(backup, table, backup_columns)
            actual = _target_table_fingerprint(target, table, target_columns)
            count = target.execute(f"SELECT COUNT(*) FROM {_quote_identifier(table)}").fetchone()[0]
            print(f"preserved {table}: rows={count} hash={actual}")
            if expected != actual:
                raise RuntimeError(f"Preserved table content changed: {table}")
    finally:
        backup.close()
        target.close()


def _check_sqlite_health(local_db: Path) -> None:
    conn = _connect(local_db)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_key_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
        print(f"integrity_check={integrity}")
        print(f"foreign_key_check_count={len(foreign_key_errors)}")
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity_check failed: {integrity}")
        if foreign_key_errors:
            raise RuntimeError(f"SQLite foreign_key_check failed: {foreign_key_errors}")
    finally:
        conn.close()


def _compare_directories(prod_data: Path, local_data: Path) -> None:
    prod = _directory_fingerprints(prod_data)
    local = _directory_fingerprints(local_data)
    for relative in [path.as_posix() for path in PRODUCTION_DIRS]:
        info = local[relative]
        print(
            f"directory {relative}: files={info['files']} bytes={info['bytes']} sha256={info['sha256']}"
        )
    if prod != local:
        raise RuntimeError("Production directory fingerprints differ from local data")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify production data migration.")
    parser.add_argument("--local-data", type=Path, default=DEFAULT_LOCAL_DATA)
    parser.add_argument("--prod-data", type=Path, default=DEFAULT_PROD_DATA)
    parser.add_argument("--backup-data", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    local_data = args.local_data.resolve()
    prod_data = args.prod_data.resolve()
    backup_data = args.backup_data.resolve()
    local_db = local_data / SQL_DB_RELATIVE
    backup_db = backup_data / SQL_DB_RELATIVE
    prod_snapshot = backup_data / "_verification_production_snapshot.sqlite"

    _create_sqlite_snapshot(prod_data / SQL_DB_RELATIVE, prod_snapshot)
    try:
        _compare_migrated_tables(prod_snapshot, local_db)
        _compare_preserved_tables(backup_db, local_db)
        _check_sqlite_health(local_db)
        _compare_directories(prod_data, local_data)
        print("Verification completed successfully.")
    finally:
        if prod_snapshot.exists():
            prod_snapshot.unlink()


if __name__ == "__main__":
    main()
