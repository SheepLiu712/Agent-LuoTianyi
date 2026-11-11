"""Instance identity, durable operation records and plan freshness checks."""

import hashlib
import json
import os
import re
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from cli import json_bytes, tomllib


class DeploymentError(RuntimeError):
    def __init__(self, message, code=5):
        super().__init__(message)
        self.code = code


def load_instance(config, name):
    mapping = tomllib.loads(Path(config).expanduser().read_text())
    instance = mapping.get("instances", {}).get(name)
    if not isinstance(instance, dict) or not Path(instance.get("root", "")).is_absolute():
        raise ValueError("未知实例或 root 不是绝对路径")
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.@-]*\.service", instance.get("service", "")):
        raise ValueError("实例 service 必须是有效的 systemd .service 名称")
    if any(c in instance["root"] for c in '\n\r\x00"\\'):
        raise ValueError("实例 root 包含不支持的字符")
    return instance


def atomic_json(path, value):
    atomic_bytes(path, json_bytes(value))


def atomic_bytes(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".deploy-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_record(path):
    if not path.exists():
        return None
    record = json.loads(path.read_text())
    if not isinstance(record, dict) or record.get("schema_version") != 1:
        raise DeploymentError("不支持的部署记录 schema", 3)
    return record


def freshness(instance, report):
    root = Path(instance["root"]).resolve()
    files = {}
    config_dir = root / "config"
    for path in sorted(config_dir.rglob("*")):
        if path.is_file():
            stat = path.stat()
            # Credential contents and their hashes are not copied into the plan.
            files[str(path.relative_to(root))] = [
                stat.st_dev,
                stat.st_ino,
                stat.st_size,
                stat.st_mtime_ns,
                stat.st_ctime_ns,
            ]
    current = root / "current"
    manifest = current / "release.json"
    root_stat = root.stat()
    databases = {}
    for name, record in report.get("databases", {}).items():
        databases[name] = dict(record)
        path = Path(record["path"])
        if path.is_file():
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
                databases[name]["current_version"] = connection.execute("PRAGMA user_version").fetchone()[0]
    return {
        "instance_mapping": hashlib.sha256(json_bytes(instance)).hexdigest(),
        "root_identity": [root_stat.st_dev, root_stat.st_ino],
        "current_path": str(current.resolve()),
        "current_manifest": hashlib.sha256(manifest.read_bytes()).hexdigest() if manifest.is_file() else None,
        "config_files": files,
        "config_sha256": report.get("config_sha256"),
        "database_versions": databases,
    }


def ensure_local_layout(root):
    for name in ("releases", "environments", "deployments", "config", "data", ".runtime"):
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise DeploymentError(f"实例目录不能通过链接指向其他位置：{name}", 3)
