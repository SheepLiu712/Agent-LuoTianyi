import argparse
import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


SERVER_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = SERVER_ROOT.parent
DEFAULT_LOCAL_DATA = SERVER_ROOT / "data"
DEFAULT_PROD_DATA = SERVER_ROOT / "data_produce"
DEFAULT_BACKUP_ROOT = SERVER_ROOT / "data_backups"
SQL_DB_RELATIVE = Path("database") / "luotianyi.db"

MIGRATED_TABLES = ("users", "invite_codes", "conversations")
RESET_LOCAL_TABLES = (
    "conversations",
    "invite_codes",
    "conversation_contexts",
    "memory_update_records",
    "memory_records",
    "knowledge_buffers",
    "affection_logs",
    "users",
)
PRESERVED_TABLES = (
    "agent_memory_records",
    "memory_chunks",
    "memory_edges",
    "events",
    "event_notifications",
)
PRODUCTION_DIRS = (
    Path("database") / "vector_store",
    Path("citywalk_reports"),
    Path("images"),
    Path("plugin_scheduler"),
)
MISSING_VALUE_FALLBACKS = {
    ("users", "preferences"): "{}",
    ("users", "affection_score"): 0,
    ("users", "affection_total_gained"): 0,
    ("conversations", "character_id"): "luotianyi",
}


def _quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def _table_columns(conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    return list(conn.execute(f"PRAGMA table_info({_quote_identifier(table)})"))


def _row_count(conn: sqlite3.Connection, table: str) -> int | None:
    if table not in _table_names(conn):
        return None
    return conn.execute(f"SELECT COUNT(*) FROM {_quote_identifier(table)}").fetchone()[0]


def _counts(conn: sqlite3.Connection, tables: tuple[str, ...]) -> dict[str, int | None]:
    return {table: _row_count(conn, table) for table in tables}


def _directory_fingerprint(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "files": 0, "bytes": 0, "sha256": None}

    digest = hashlib.sha256()
    file_count = 0
    total_bytes = 0
    for file_path in sorted(item for item in path.rglob("*") if item.is_file()):
        relative = file_path.relative_to(path).as_posix()
        data = file_path.read_bytes()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(data).digest())
        file_count += 1
        total_bytes += len(data)

    return {
        "exists": True,
        "files": file_count,
        "bytes": total_bytes,
        "sha256": digest.hexdigest(),
    }


def _directory_fingerprints(root: Path) -> dict[str, dict[str, Any]]:
    return {
        relative.as_posix(): _directory_fingerprint(root / relative)
        for relative in PRODUCTION_DIRS
    }


def _ensure_inside(path: Path, root: Path) -> None:
    resolved_path = path.resolve()
    resolved_root = root.resolve()
    if resolved_path != resolved_root and resolved_root not in resolved_path.parents:
        raise RuntimeError(f"Refusing to operate outside {resolved_root}: {resolved_path}")


def _find_running_server_processes() -> list[dict[str, str]]:
    if os.name != "nt":
        return []

    command = (
        "Get-CimInstance Win32_Process -Filter \"name = 'python.exe'\" | "
        "Where-Object { $_.CommandLine -match 'server_main\\.py|server_main.py' } | "
        "Select-Object ProcessId,CommandLine | ConvertTo-Json"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    output = result.stdout.strip()
    if not output:
        return []

    import json

    data = json.loads(output)
    if isinstance(data, dict):
        data = [data]
    return [
        {"pid": str(item.get("ProcessId")), "command": str(item.get("CommandLine"))}
        for item in data
    ]


def _create_sqlite_snapshot(source_db: Path, snapshot_db: Path) -> None:
    snapshot_db.parent.mkdir(parents=True, exist_ok=True)
    if snapshot_db.exists():
        snapshot_db.unlink()

    source = _connect(source_db)
    try:
        target = _connect(snapshot_db)
        try:
            source.backup(target)
            target.commit()
        finally:
            target.close()
    finally:
        source.close()


def _run_local_schema_migration(local_data: Path) -> None:
    sys.path.insert(0, str(SERVER_ROOT))
    from src.system.database import sql_database

    sql_database.init_sql_db(
        str(local_data / "database"),
        "luotianyi.db",
    )
    if sql_database.engine is not None:
        sql_database.engine.dispose()


def _literal_sql(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _compile_sqlite_type(column: Any) -> str:
    from sqlalchemy.dialects import sqlite

    return column.type.compile(dialect=sqlite.dialect())


def _column_default_value(table_name: str, column: Any) -> Any:
    key = (table_name, column.name)
    if key in MISSING_VALUE_FALLBACKS:
        return MISSING_VALUE_FALLBACKS[key]

    default = column.default
    if default is not None and not default.is_callable and not default.is_sequence:
        return default.arg

    server_default = column.server_default
    if server_default is not None and getattr(server_default, "arg", None) is not None:
        text = str(server_default.arg)
        if text.startswith("'") and text.endswith("'"):
            return text[1:-1]
        return text

    return None


def _add_missing_model_columns(target_db: Path) -> None:
    sys.path.insert(0, str(SERVER_ROOT))
    from src.system.database.sql_database import Base

    conn = _connect(target_db)
    try:
        existing_tables = _table_names(conn)
        for table in Base.metadata.sorted_tables:
            table_name = table.name
            if table_name not in existing_tables:
                continue

            existing_columns = {row["name"] for row in _table_columns(conn, table_name)}
            for column in table.columns:
                if column.name in existing_columns:
                    continue
                if column.primary_key:
                    raise RuntimeError(f"Cannot add missing primary key column {table_name}.{column.name}")

                ddl = (
                    f"ALTER TABLE {_quote_identifier(table_name)} "
                    f"ADD COLUMN {_quote_identifier(column.name)} {_compile_sqlite_type(column)}"
                )
                default_value = _column_default_value(table_name, column)
                if default_value is not None:
                    ddl += f" DEFAULT {_literal_sql(default_value)}"
                if not column.nullable:
                    if default_value is None:
                        raise RuntimeError(
                            f"Missing non-null column {table_name}.{column.name} has no safe default"
                        )
                    ddl += " NOT NULL"
                conn.execute(ddl)
                existing_columns.add(column.name)
        conn.commit()
    finally:
        conn.close()


def _fallback_for_missing_value(table: str, column_info: sqlite3.Row) -> Any:
    key = (table, column_info["name"])
    if key in MISSING_VALUE_FALLBACKS:
        return MISSING_VALUE_FALLBACKS[key]
    if column_info["dflt_value"] is not None:
        default = str(column_info["dflt_value"])
        if default.startswith("'") and default.endswith("'"):
            return default[1:-1]
        if default.upper() == "NULL":
            return None
        try:
            return int(default)
        except ValueError:
            return default
    return None


def _copy_table_rows(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    table: str,
) -> int:
    source_columns = {row["name"] for row in _table_columns(source, table)}
    target_columns = _table_columns(target, table)
    target_column_names = [row["name"] for row in target_columns]
    select_columns = [name for name in target_column_names if name in source_columns]

    select_sql = (
        f"SELECT {', '.join(_quote_identifier(name) for name in select_columns)} "
        f"FROM {_quote_identifier(table)}"
    )
    insert_sql = (
        f"INSERT INTO {_quote_identifier(table)} "
        f"({', '.join(_quote_identifier(name) for name in target_column_names)}) "
        f"VALUES ({', '.join('?' for _ in target_column_names)})"
    )

    copied = 0
    for row in source.execute(select_sql):
        values = []
        for column_info in target_columns:
            name = column_info["name"]
            if name in source_columns:
                values.append(row[name])
            else:
                values.append(_fallback_for_missing_value(table, column_info))
        target.execute(insert_sql, values)
        copied += 1
    return copied


def _migrate_sql_tables(prod_snapshot_db: Path, target_db: Path) -> dict[str, int]:
    source = _connect(prod_snapshot_db)
    target = _connect(target_db)
    try:
        for table in MIGRATED_TABLES:
            if table not in _table_names(source):
                raise RuntimeError(f"Production database is missing required table: {table}")
            if table not in _table_names(target):
                raise RuntimeError(f"Local database is missing required table: {table}")

        target.execute("PRAGMA foreign_keys=OFF")
        target.execute("BEGIN")
        try:
            target_tables = _table_names(target)
            for table in RESET_LOCAL_TABLES:
                if table in target_tables:
                    target.execute(f"DELETE FROM {_quote_identifier(table)}")

            copied: dict[str, int] = {}
            for table in MIGRATED_TABLES:
                copied[table] = _copy_table_rows(source, target, table)

            target.commit()
            return copied
        except Exception:
            target.rollback()
            raise
    finally:
        source.close()
        target.close()


def _replace_directory(source: Path, target: Path, local_data: Path) -> None:
    _ensure_inside(target, local_data)
    if not source.exists():
        raise RuntimeError(f"Production directory is missing: {source}")

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)


def _replace_production_directories(prod_data: Path, local_data: Path) -> None:
    for relative in PRODUCTION_DIRS:
        _replace_directory(prod_data / relative, local_data / relative, local_data)


def _backup_local_data(local_data: Path, backup_root: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = backup_root / f"pre_production_migration_{timestamp}"
    if backup_dir.exists():
        raise RuntimeError(f"Backup directory already exists: {backup_dir}")
    backup_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(local_data, backup_dir)
    return backup_dir


def _cleanup_temp_snapshot(prod_snapshot_db: Path, temp_root: Path) -> None:
    if prod_snapshot_db.exists():
        prod_snapshot_db.unlink()
    try:
        temp_root.rmdir()
    except OSError:
        pass


def _print_counts(label: str, counts: dict[str, int | None]) -> None:
    print(f"{label}:")
    for table, count in counts.items():
        print(f"  {table}: {count}")


def _print_fingerprints(label: str, fingerprints: dict[str, dict[str, Any]]) -> None:
    print(f"{label}:")
    for relative, info in fingerprints.items():
        print(
            f"  {relative}: exists={info['exists']} files={info['files']} "
            f"bytes={info['bytes']} sha256={info['sha256']}"
        )


def _validate(
    prod_snapshot_db: Path,
    target_db: Path,
    before_preserved_counts: dict[str, int | None],
    prod_dir_fingerprints: dict[str, dict[str, Any]],
    local_data: Path,
) -> None:
    prod = _connect(prod_snapshot_db)
    target = _connect(target_db)
    try:
        prod_counts = _counts(prod, MIGRATED_TABLES)
        target_counts = _counts(target, MIGRATED_TABLES)
        if prod_counts != target_counts:
            raise RuntimeError(f"Migrated table counts differ: prod={prod_counts}, target={target_counts}")

        after_preserved_counts = _counts(target, PRESERVED_TABLES)
        if before_preserved_counts != after_preserved_counts:
            raise RuntimeError(
                "Local-preserved table counts changed: "
                f"before={before_preserved_counts}, after={after_preserved_counts}"
            )

        integrity = target.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity_check failed: {integrity}")
        foreign_key_errors = target.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_errors:
            raise RuntimeError(f"SQLite foreign_key_check failed: {foreign_key_errors}")
    finally:
        prod.close()
        target.close()

    local_dir_fingerprints = _directory_fingerprints(local_data)
    if prod_dir_fingerprints != local_dir_fingerprints:
        raise RuntimeError(
            "Production directory fingerprints differ after copy: "
            f"prod={prod_dir_fingerprints}, local={local_dir_fingerprints}"
        )


def run(args: argparse.Namespace) -> None:
    local_data = args.local_data.resolve()
    prod_data = args.prod_data.resolve()
    backup_root = args.backup_root.resolve()
    local_db = local_data / SQL_DB_RELATIVE
    prod_db = prod_data / SQL_DB_RELATIVE

    if not local_db.exists():
        raise RuntimeError(f"Local database is missing: {local_db}")
    if not prod_db.exists():
        raise RuntimeError(f"Production database is missing: {prod_db}")

    running = _find_running_server_processes()
    if running and not args.force:
        print("Detected running server_main.py process(es):")
        for item in running:
            print(f"  PID {item['pid']}: {item['command']}")
        raise RuntimeError("Stop the server before migration, or rerun with --force.")

    temp_root = backup_root / "_tmp"
    temp_root.mkdir(parents=True, exist_ok=True)
    prod_snapshot_db = temp_root / "production_snapshot.sqlite"

    _create_sqlite_snapshot(prod_db, prod_snapshot_db)

    prod_conn = _connect(prod_snapshot_db)
    local_conn = _connect(local_db)
    try:
        prod_counts = _counts(prod_conn, MIGRATED_TABLES)
        local_migrated_counts = _counts(local_conn, MIGRATED_TABLES)
        before_preserved_counts = _counts(local_conn, PRESERVED_TABLES)
    finally:
        prod_conn.close()
        local_conn.close()

    prod_dir_fingerprints = _directory_fingerprints(prod_data)
    local_dir_fingerprints = _directory_fingerprints(local_data)

    _print_counts("Production tables to migrate", prod_counts)
    _print_counts("Current local tables to replace", local_migrated_counts)
    _print_counts("Current local tables to preserve", before_preserved_counts)
    _print_fingerprints("Production directories to copy", prod_dir_fingerprints)
    _print_fingerprints("Current local directories to replace", local_dir_fingerprints)

    if args.dry_run:
        print("Dry-run complete; no data was modified.")
        _cleanup_temp_snapshot(prod_snapshot_db, temp_root)
        return

    backup_dir = _backup_local_data(local_data, backup_root)
    print(f"Backed up local data to: {backup_dir}")

    _run_local_schema_migration(local_data)
    _add_missing_model_columns(local_db)
    copied = _migrate_sql_tables(prod_snapshot_db, local_db)
    _replace_production_directories(prod_data, local_data)
    _validate(
        prod_snapshot_db,
        local_db,
        before_preserved_counts,
        prod_dir_fingerprints,
        local_data,
    )

    _print_counts("Copied table rows", copied)
    _cleanup_temp_snapshot(prod_snapshot_db, temp_root)
    print("Migration completed and verified.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate production data_produce into local data while preserving local memory/event tables."
    )
    parser.add_argument("--local-data", type=Path, default=DEFAULT_LOCAL_DATA)
    parser.add_argument("--prod-data", type=Path, default=DEFAULT_PROD_DATA)
    parser.add_argument("--backup-root", type=Path, default=DEFAULT_BACKUP_ROOT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="Run even if server_main.py is detected.")
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
