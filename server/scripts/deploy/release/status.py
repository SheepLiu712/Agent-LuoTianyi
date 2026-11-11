"""Read actual service state separately from the last successful deployment record."""

import json
from pathlib import Path

from deployment_state import DeploymentError, load_instance, read_record
from offline_steps import runtime_bindings
from plan import check_tree
from service_control import Systemd, actual_release, health, process_bindings


def operation_record(root):
    latest = read_record(root / "deployments/latest.json")
    if latest is None:
        return None
    identifier = latest["operation_id"]
    if not isinstance(identifier, str) or Path(identifier).name != identifier or identifier in {".", ".."}:
        raise ValueError("Invalid operation identity")
    return read_record(root / "deployments/operations" / identifier / "operation.json") or latest


def status(config, name):
    instance = load_instance(config, name)
    root = Path(instance["root"]).resolve()
    result = {"instance": name, "root": str(root), "service": instance["service"], "warnings": []}
    for field, file in (("last_success", "current.json"), ("latest_operation", "latest.json")):
        try:
            result[field] = (
                operation_record(root) if field == "latest_operation" else read_record(root / "deployments" / file)
            )
        except (DeploymentError, OSError, ValueError, KeyError):
            result[field] = None
            result["warnings"].append(f"无法读取或不支持部署记录 {file}")
    current = root / "current"
    result["selected_release"] = None
    try:
        if not current.is_symlink() or current.resolve().parent != root / "releases":
            raise ValueError("current does not belong to this instance")
        manifest = json.loads((current / "release.json").read_text())
        if manifest["schema_version"] != 1 or manifest["release_id"] != current.resolve().name:
            raise ValueError("schema")
        result["release_files_valid"] = not check_tree(current.resolve(), manifest["files"])
        if not result["release_files_valid"]:
            result["warnings"].append("当前发布文件与校验清单不一致")
        result["selected_release"] = manifest["release_id"]
        result["selected_commit"] = manifest["commit_sha"]
        result["selected_assets"] = manifest["assets"]["version"]
        result["selected_environment"] = manifest["environment"]["environment_id"]
        result["expected_runtime_paths"] = runtime_bindings(
            root,
            current.resolve(),
            root / "environments" / result["selected_environment"],
            root / "assets" / result["selected_assets"],
        )
    except (OSError, ValueError, KeyError):
        result["warnings"].append("当前发布清单不存在或不受支持")
    try:
        state = Systemd(instance).query()
        result["service_state"] = {
            key: state.get(key) for key in ("LoadState", "ActiveState", "SubState", "MainPID", "NRestarts")
        }
        result["actual_release"] = actual_release(state, root)
        result["runtime_paths"] = process_bindings(state)
    except DeploymentError:
        state = {}
        result["service_state"] = {"ActiveState": "unknown"}
        result["actual_release"] = None
        result["warnings"].append("无法查询 systemd 状态")
    result["health"] = health(instance)
    result["healthy"] = (
        state.get("ActiveState") == "active"
        and result["health"]["healthy"]
        and result["actual_release"] is not None
        and result["actual_release"] == result["selected_release"]
        and result.get("release_files_valid", False)
        and result.get("runtime_paths") == result.get("expected_runtime_paths")
    )
    recorded = (result["last_success"] or {}).get("release_id")
    if recorded != result["actual_release"]:
        result["warnings"].append("最近成功部署记录与实际运行版本不一致")
    return result
