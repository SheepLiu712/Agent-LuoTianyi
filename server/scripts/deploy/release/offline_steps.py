"""Offline backups, writer exclusion, migrations and atomic version switching."""

import fcntl
import json
import os
import shutil
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from cli import check_path, file_digest
from deployment_state import DeploymentError, atomic_bytes, atomic_json
from plan_database import inspect_database
from release_contract import effective_config
from service_control import run


@contextmanager
def runtime_lock(root):
    runtime = root / ".runtime"
    runtime.mkdir(exist_ok=True, mode=0o700)
    with (runtime / "server.lock").open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DeploymentError("实例写入锁仍被占用，拒绝迁移") from None
        yield


def ensure_no_writers(root, *, check_only=False):
    for process in Path("/proc").iterdir():
        if not process.name.isdecimal() or int(process.name) == os.getpid():
            continue
        try:
            if process.stat().st_uid != os.getuid():
                continue
            references = [process / "cwd", *(process / "fd").iterdir()]
            for entry in references:
                target = entry.resolve()
                if not check_only and (
                    target.is_relative_to(root / "data") or target.is_relative_to(root / ".runtime")
                ):
                    raise DeploymentError(f"实例仍有写入进程 PID {process.name}，拒绝离线迁移")
        except FileNotFoundError:
            continue
        except PermissionError:
            raise DeploymentError(f"无法检查同用户进程 PID {process.name} 的数据库访问") from None


def verify_writers(root, instance, *, check_only=False):
    mode = instance.get("writer_check", "local")
    if mode == "local":
        return ensure_no_writers(root, check_only=check_only)
    if mode != "sudo-helper":
        raise DeploymentError("writer_check 必须为 local 或 sudo-helper", 3)
    command = ["sudo", "-n", "/usr/local/libexec/agentluo-check-writers", "--root", str(root)]
    if check_only:
        command.append("--check-only")
    run(command, timeout=30)


def verify_existing_backup(root, directory, report):
    directory = Path(directory).resolve()
    if not directory.is_relative_to(root / "deployments"):
        raise DeploymentError("复用备份必须位于本实例 deployments 中", 3)
    record = json.loads((directory / "reuse.json").read_text())
    if record.get("schema_version") != 1 or record.get("root") != str(root):
        raise DeploymentError("已有备份的实例身份不匹配", 3)
    if record.get("current_release_sha256") != file_digest(root / "current/release.json"):
        raise DeploymentError("已有备份不对应当前发布", 3)
    required = {str(path.relative_to(root)) for path in (root / "config").rglob("*") if path.is_file()}
    required.update(str(Path(item["path"]).relative_to(root)) for item in report["databases"].values())
    backup_required = {str(path.relative_to(root)) for path in (root / "config").rglob("*") if path.is_file()}
    backup_required.update(kind + ".sqlite" for kind in report["databases"])
    if not backup_required <= record["backup_files"].keys():
        raise DeploymentError("已有备份未包含完整配置与数据库副本", 3)
    if not required <= record["source_files"].keys():
        raise DeploymentError("已有备份缺少实例配置或数据库状态记录", 3)
    for base, files in ((root, record["source_files"]), (directory, record["backup_files"])):
        for name, checksum in files.items():
            check_path(name)
            if file_digest(base / name) != checksum:
                raise DeploymentError("已有备份或源文件已经变化，不能复用", 3)
    return str(directory)


def backup(root, operation, report, *, reuse=None):
    if reuse is not None:
        return verify_existing_backup(root, reuse, report)
    target = root / "deployments/backups" / operation
    target.mkdir(parents=True, mode=0o700)
    shutil.copytree(root / "config", target / "config", symlinks=False)
    current = root / "current/release.json"
    shutil.copy2(current, target / "previous-release.json")
    environment = root / "deployments/instance.env"
    if environment.exists():
        shutil.copy2(environment, target / "instance.env")
    for migration in report["migrations"]:
        source = Path(migration["database"])
        destination = target / (migration["kind"] + ".sqlite")
        destination.touch(mode=0o600)
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as database:
            with closing(sqlite3.connect(destination)) as copy:
                database.backup(copy)
                copy.execute("PRAGMA journal_mode=DELETE")
                if copy.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise DeploymentError("数据库备份校验失败")
    inventory = {}
    for path in target.rglob("*"):
        if path.is_file():
            path.chmod(0o600)
            inventory[str(path.relative_to(target))] = file_digest(path)
    atomic_json(target / "backup.json", {"schema_version": 1, "files": inventory})
    return str(target)


def migrate(release, environment, manifest, report, record_step):
    for step in report["migrations"]:
        record_step("migrating", migration=step["kind"])
        run(
            [
                str(environment / "bin/python"),
                str(release / step["entrypoint"]),
                "--kind",
                step["kind"],
                "--database",
                step["database"],
            ],
            timeout=1800,
        )
        record_step("migration_completed", migration=step["kind"])
    for kind, requirement in manifest["databases"].items():
        version, errors = inspect_database(Path(report["databases"][kind]["path"]), requirement)
        if version != requirement["version"] or errors:
            raise DeploymentError(f"{kind}: 迁移后的 schema 验证失败")


def switch(root, release, environment, assets, instance):
    # Only the ordinary config is replaced; credentials remain in their original files.
    config = effective_config(json.loads((release / "config/config.json").read_text()), instance)
    atomic_json(root / "config/config.json", config)
    values = {
        **runtime_bindings(root, release, environment, assets),
        "PYTHONDONTWRITEBYTECODE": "1",
        "SERVER_HOST": instance.get("host", "127.0.0.1"),
    }
    lines = []
    for key, value in values.items():
        text = str(value)
        if any(character in text for character in '\n\r\x00"\\'):
            raise DeploymentError("实例路径不能包含换行、引号或反斜杠", 3)
        lines.append(f'{key}="{text}"')
    atomic_bytes(root / "deployments/instance.env", ("\n".join(lines) + "\n").encode())
    temporary = root / ".current-next"
    if temporary.exists() or temporary.is_symlink():
        raise DeploymentError("存在未完成的版本切换 .current-next，请人工检查")
    temporary.symlink_to(release)
    os.replace(temporary, root / "current")


def runtime_bindings(root, release, environment, assets):
    return {
        "AGENTLUO_CONFIG_DIR": str(root / "config"),
        "AGENTLUO_DATA_DIR": str(root / "data"),
        "AGENTLUO_RUNTIME_DIR": str(root / ".runtime"),
        "AGENTLUO_ASSET_DIR": str(assets),
        "AGENTLUO_RESOURCE_DIR": str(release / "res"),
        "AGENTLUO_PYTHON": str(environment / "bin/python"),
        "PLAYWRIGHT_BROWSERS_PATH": str(environment / "browsers"),
    }
