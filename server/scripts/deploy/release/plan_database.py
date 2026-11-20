"""Read database versions and produce offline migration steps; never write a database."""

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

from release_contract import database_paths, validate_config

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from src.utils.database_schema import inspect_database  # noqa: E402


def inspect_databases(root, manifest, result):
    result["databases"] = {}
    result["migrations"] = []
    for kind, requirement in manifest["databases"].items():
        path = root / requirement["path"]
        record = {"path": str(path), "target_version": requirement["version"]}
        result["databases"][kind] = record
        if not path.resolve().is_relative_to((root / "data").resolve()) or not path.is_file():
            result["blockers"].append(f"{kind}: 数据库缺失或路径越界，不会创建空库替代")
            continue
        try:
            version, errors = inspect_database(path, requirement)
        except sqlite3.Error:
            result["blockers"].append(f"{kind}: 无法读取 SQLite schema")
            continue
        record["current_version"] = version
        result["blockers"].extend(f"{kind}: {error}" for error in errors)
        if version != requirement["version"]:
            migration = next(
                (
                    item
                    for item in manifest["database_migrations"]
                    if item["from"] == version and item["to"] == requirement["version"]
                ),
                None,
            )
            if migration is None:
                result["blockers"].append(f"{kind}: schema {version} 没有到 {requirement['version']} 的迁移路径")
            else:
                result["migrations"].append(
                    {
                        **migration,
                        "kind": kind,
                        "database": str(path),
                        "requires_stop": True,
                        "backup": "sqlite_backup_before_migration",
                    }
                )


def inspect_configuration(root, manifest, result):
    result["configuration"] = {**manifest["configuration"], "preserve": "all_other_instance_config_files"}
    existing = root / "config/config.json"
    if not existing.is_file():
        return
    content = existing.read_bytes()
    result["config_sha256"] = hashlib.sha256(content).hexdigest()
    old = json.loads(content)
    try:
        validate_config(old)
    except ValueError:
        result["blockers"].append("旧普通配置包含内联凭据，请先移入实例密钥存储并改为环境变量引用")
    try:
        old_paths = database_paths(old)
    except (KeyError, ValueError, TypeError):
        result["blockers"].append("无法确认旧配置的数据库位置，请先明确现有数据库映射")
        return
    if old_paths != {kind: item["path"] for kind, item in manifest["databases"].items()}:
        result["blockers"].append("覆盖配置会改变数据库路径；需先明确数据目录迁移，不允许切换到空库")
