"""Apply a bound plan with exclusive locking and durable phase records."""

import fcntl
import json
import shutil
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from cli import file_digest
from deployment_state import (
    DeploymentError,
    atomic_json,
    ensure_local_layout,
    freshness,
    load_instance,
    read_record,
)
from offline_steps import (
    backup,
    migrate,
    runtime_bindings,
    runtime_lock,
    switch,
    verify_existing_backup,
    verify_writers,
)
from plan import inspect, read_package
from prepare_release import check_startup, prepare_assets, prepare_environment, prepare_release
from service_control import Systemd, await_healthy, validate_urls


@contextmanager
def deployment_lock(root):
    directory = root / "deployments"
    directory.mkdir(exist_ok=True, mode=0o700)
    with (directory / "deploy.lock").open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DeploymentError("同一实例已有部署正在进行", 4) from None
        yield


def check_pending(root):
    pending_link = root / ".current-next"
    if pending_link.exists() or pending_link.is_symlink():
        raise DeploymentError("存在未完成的 .current-next 切换，请先人工恢复并重新生成计划", 3)
    for path in (root / "deployments/operations").glob("*/operation.json"):
        record = read_record(path)
        if (record["outcome"] == "running" or record.get("requires_recovery")) and not record.get(
            "recovery_acknowledged"
        ):
            raise DeploymentError(
                f"存在未完成操作 {record['operation_id']}；请检查阶段记录、实际服务和备份，完成恢复后在该记录标记 "
                "recovery_acknowledged=true，并重新生成计划。不得盲目重跑迁移。",
                3,
            )


def inspect_again(document, instance):
    package = Path(document["package"])
    if file_digest(package) != document["package_sha256"]:
        raise DeploymentError("发布包已变化，请重新生成计划", 3)
    manifest, assets, lock = read_package(package)
    if manifest["release_id"] != document["target_release"]:
        raise DeploymentError("计划目标与发布包不一致，请重新生成计划", 3)
    report = {"blockers": [], "components": {}, "expected_current_release": None}
    inspect(instance, manifest, assets, lock, report)
    for kind in ("release", "environment"):
        if Path(report["components"][kind]["path"]).is_symlink():
            report["blockers"].append(f"{kind}: 版本目录不能是符号链接")
    if report["blockers"]:
        raise DeploymentError("预检阻断：" + "; ".join(report["blockers"]), 3)
    return manifest, assets, lock, report


def check_fresh(document, instance, report):
    for field in ("expected_current_release", "migrations", "configuration"):
        if document.get(field) != report.get(field):
            raise DeploymentError(f"计划中的 {field} 与重新检查结果不一致，请重新生成计划", 3)
    if freshness(instance, report) != document["freshness"]:
        raise DeploymentError("实例映射、当前发布、配置或数据库版本发生变化，请重新生成计划", 3)


def space_for_backup(root, report):
    needed = sum(p.stat().st_size for p in (root / "config").rglob("*") if p.is_file())
    for step in report["migrations"]:
        path = Path(step["database"])
        # Coordinator backup plus the legacy migrator's independent recovery copy.
        needed += path.stat().st_size * 2
        wal = Path(str(path) + "-wal")
        if wal.exists():
            needed += wal.stat().st_size * 2
    if shutil.disk_usage(root).free < needed + 1024 * 1024:
        raise DeploymentError("数据库及配置备份空间不足", 3)


def no_change(root, document, instance, report, controller):
    record = read_record(root / "deployments/current.json")
    if not record or record.get("package_sha256") != document["package_sha256"]:
        return False
    if record.get("freshness") != freshness(instance, report):
        return False
    from service_control import actual_release, health, process_bindings

    state = controller.query()
    return (
        state.get("ActiveState") == "active"
        and actual_release(state, root) == document["target_release"]
        and health(instance)["healthy"]
        and process_bindings(state)
        == runtime_bindings(root, (root / "current").resolve(), Path(record["environment"]), Path(record["assets"]))
    )


class Operation:
    def __init__(self, root, document):
        self.root = root
        self.id = str(uuid.uuid4())
        self.directory = root / "deployments/operations" / self.id
        self.record = {
            "schema_version": 1,
            "operation_id": self.id,
            "started_at": time.time(),
            "outcome": "running",
            "source_release": document["expected_current_release"],
            "target_release": document["target_release"],
            "package_sha256": document["package_sha256"],
            "phases": [],
            "requires_recovery": False,
        }
        atomic_json(self.directory / "plan.json", document)

    def phase(self, phase, **details):
        self.record.update(phase=phase, **details)
        self.record["phases"].append({"phase": phase, "time": time.time(), **details})
        atomic_json(self.directory / "operation.json", self.record)
        atomic_json(self.root / "deployments/latest.json", self.record)


def execute(root, document, instance, controller, manifest, assets, lock, report, *, reuse_backup=None):
    operation = Operation(root, document)
    try:
        operation.phase("preparing")
        release = prepare_release(Path(document["package"]), root, manifest)
        asset_dir = prepare_assets(root, manifest, assets, instance)
        environment = prepare_environment(root, release, manifest, lock)
        operation.phase("preflight")
        check_startup(root, release, environment, asset_dir, instance)
        # Recheck after online preparation, before issuing any stop command.
        _, _, _, report = inspect_again(document, instance)
        check_fresh(document, instance, report)
        controller.preflight(root)
        space_for_backup(root, report)
        verify_writers(root, instance, check_only=True)
        if reuse_backup is not None:
            verify_existing_backup(root, reuse_backup, report)
        operation.phase("stopping", requires_recovery=True)
        controller.stop()
        operation.phase("stopped")
        with runtime_lock(root):
            verify_writers(root, instance)
            check_fresh(document, instance, report)
            space_for_backup(root, report)
            operation.phase("backing_up")
            backup_path = backup(root, operation.id, report, reuse=reuse_backup)
            operation.phase("backed_up", backup=backup_path)
            migrate(release, environment, manifest, report, operation.phase)
            operation.phase("switching")
            switch(root, release, environment, asset_dir, instance)
        operation.phase("starting")
        controller.start()
        operation.phase("accepting")
        result = await_healthy(
            controller, instance, manifest["release_id"], runtime_bindings(root, release, environment, asset_dir)
        )
        # Record the actual resulting database versions, not the pre-migration versions.
        _, _, _, after = inspect_again(document, instance)
        deployment = {
            "schema_version": 1,
            "release_id": manifest["release_id"],
            "commit_sha": manifest["commit_sha"],
            "package_sha256": document["package_sha256"],
            "operation_id": operation.id,
            "environment": str(environment),
            "assets": str(asset_dir),
            "freshness": freshness(instance, after),
        }
        atomic_json(root / "deployments/current.json", deployment)
        operation.phase("completed", outcome="succeeded", requires_recovery=False, health=result)
        return operation.record, 0
    except Exception as error:
        cleanup_error = None
        if operation.record["requires_recovery"]:
            try:
                controller.stop()
            except Exception:
                cleanup_error = "无法确认服务已停止，请立即人工检查 systemd 和实例写入进程"
        message = str(error) if isinstance(error, DeploymentError) else f"部署异常：{type(error).__name__}"
        operation.phase(
            "failed",
            outcome="failed",
            error=message,
            cleanup_error=cleanup_error,
            recovery="检查阶段日志与备份；修补后前进。恢复数据库前确认无新增业务写入。",
        )
        return operation.record, error.code if isinstance(error, DeploymentError) else 5


def apply(plan_path, *, reuse_backup=None):
    document = json.loads(Path(plan_path).read_text())
    if document.get("schema_version") != 2 or document.get("executable") is not True:
        raise DeploymentError("计划不可执行或版本不受支持，请重新生成计划", 3)
    instance = load_instance(document["config_path"], document["instance"])
    root = Path(instance["root"]).resolve()
    if str(root) != document["root"]:
        raise DeploymentError("实例真实路径发生变化", 3)
    ensure_local_layout(root)
    validate_urls(instance)
    controller = Systemd(instance)
    with deployment_lock(root):
        check_pending(root)
        manifest, assets, lock, report = inspect_again(document, instance)
        controller.preflight(root)
        if no_change(root, document, instance, report, controller):
            return {"outcome": "unchanged", "release_id": manifest["release_id"]}, 0
        check_fresh(document, instance, report)
        for path in (root / "config").rglob("*"):
            if path.is_symlink():
                raise DeploymentError("实例配置包含符号链接，请先明确其归属", 3)
        space_for_backup(root, report)
        return execute(root, document, instance, controller, manifest, assets, lock, report, reuse_backup=reuse_backup)
