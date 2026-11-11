"""只读部署预检；不执行包内代码或导入业务运行时。"""

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import uuid
from pathlib import Path

from cli import ASSETS, LOCK, check_path, environment, file_digest, json_bytes, locked_files, tomllib
from deployment_state import DeploymentError, freshness, load_instance
from plan_database import inspect_configuration, inspect_databases
from release_contract import declarations
from service_control import validate_urls


def read_package(path):
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        if any(not item.isfile() for item in members):
            raise ValueError("发布包只允许普通文件")
        names = [item.name for item in members]
        if len(set(names)) != len(names):
            raise ValueError("发布包路径重复")
        manifest = json.load(archive.extractfile("release.json"))
        if manifest["schema_version"] != 1 or manifest["tool_version"] != 1:
            raise ValueError("不支持的发布清单版本")
        inventory = locked_files(manifest, ("",))
        if set(names) != set(inventory) | {"release.json"}:
            raise ValueError("发布包文件与清单不一致")
        files = {}
        for name, entry in inventory.items():
            data = archive.extractfile(name).read()
            if len(data) != entry["size"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
                raise ValueError(f"发布文件损坏：{name}")
            files[name] = data
        return validate_requirements(manifest, files)


def validate_requirements(manifest, files):
    for key, value in declarations(files).items():
        if manifest.get(key) != value:
            raise ValueError(f"发布声明与文件不一致：{key}")
    if environment(files) != manifest["environment"]:
        raise ValueError("环境要求与依赖锁不一致")
    assets = json.loads(files[ASSETS])
    if (
        assets["asset_version"] != manifest["assets"]["version"]
        or hashlib.sha256(files[ASSETS]).hexdigest() != manifest["assets"]["lock_sha256"]
    ):
        raise ValueError("资产要求与资产清单不一致")
    locked_files(assets, ("tts/", "song_learner/"))
    for identifier in (manifest["release_id"], assets["asset_version"], manifest["environment"]["environment_id"]):
        if not identifier or Path(identifier).name != identifier or identifier in {".", ".."}:
            raise ValueError("非法版本标识")
    return manifest, assets, tomllib.loads(files[LOCK].decode())


def check_tree(root, entries):
    problems = []
    for entry in entries:
        check_path(entry["path"])
        path = root / entry["path"]
        if not path.resolve().is_relative_to(root.resolve()):
            problems.append(f"路径越界：{entry['path']}")
        elif not path.is_file():
            problems.append(f"缺少文件：{entry['path']}")
        elif path.stat().st_size != entry["size"] or file_digest(path) != entry["sha256"]:
            problems.append(f"校验不一致：{entry['path']}")
    return problems


def check_environment(root, requirement, lock):
    python = root / "bin/python"
    if not python.is_file():
        return ["Python 解释器缺失"]
    # -I 隔离用户环境；只查询解释器和安装元数据，不加载模型或启动服务。
    try:
        result = subprocess.run(
            [str(python), "-I", str(Path(__file__).with_name("probe_environment.py"))],
            input=json.dumps(lock),
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        actual = json.loads(result.stdout)
        if actual["platform"] != "linux" or actual["machine"] != "x86_64":
            return ["环境平台不匹配：要求 Linux x86_64"]
        if "playwright" in actual["packages"] and not (root / "browsers").is_dir():
            return ["环境缺少独立 Chromium 浏览器目录"]
        marker = json.loads((root / "environment.json").read_text())
        if marker != requirement or actual["python"] != requirement["python_version"]:
            return ["环境标识或 Python 版本不一致"]
        if actual["packages"].get("torch") != requirement["torch_version"]:
            return ["PyTorch 版本不一致"]
        errors = check_locked_packages(actual["packages"], actual["required"])
        if errors:
            return errors
        command = (
            [shutil.which("uv"), "pip", "check", "--python", str(python)]
            if shutil.which("uv")
            else [str(python), "-I", "-m", "pip", "check"]
        )
        check = subprocess.run(command, capture_output=True, timeout=30)
        if check.returncode:
            return ["Python 依赖检查失败或 pip 不可用"]
    except (OSError, ValueError, subprocess.SubprocessError):
        return ["无法验证 Python 环境及 environment.json"]
    return []


def check_locked_packages(installed, required):
    for name, version in required.items():
        if installed.get(name) != version:
            return [f"锁定依赖缺失或版本不一致：{name}"]
    return []


def inspect_components(root, manifest, assets, result, instance):
    targets = [
        ("release", root / "releases" / manifest["release_id"], manifest["files"]),
        ("assets", root / "assets" / assets["asset_version"], assets["files"]),
    ]
    for kind, target, entries in targets:
        errors = check_tree(target, entries) if target.exists() else []
        if kind == "release" and target.exists():
            record = target / "release.json"
            if not record.is_file() or json.loads(record.read_text()) != manifest:
                errors.append("已存在发布目录的清单与目标包不一致")
        result["components"][kind] = {
            "path": str(target),
            "action": "blocked" if errors else ("prepare" if not target.exists() else "reuse"),
            "problems": errors,
        }
        result["blockers"].extend(f"{kind}: {error}" for error in errors)
        if kind == "assets" and not target.exists():
            source = Path(instance.get("asset_source", ""))
            if not source.is_absolute() or not source.is_dir():
                result["blockers"].append("模型资产缺失：请在实例映射中声明绝对路径 asset_source")
            else:
                result["blockers"].extend(check_tree(source, assets["files"]))
                result["components"][kind]["source"] = str(source.resolve())


def inspect_config_and_space(root, manifest, result):
    inspect_configuration(root, manifest, result)
    inspect_databases(root, manifest, result)
    result["requires_stop"] = True
    result["acceptance"] = ["database_schema", "systemd_active", "health", "runtime_running", "admin_ui"]
    result["failure_policy"] = "keep_stopped_on_migration_failure; preserve_backups; fix_forward"
    result["backup"] = ["instance_config", "current_release_record", "databases_before_migration"]
    existing = root
    while not existing.exists():
        existing = existing.parent
    required = sum(e["size"] for e in manifest["files"])
    result["space"] = {"release_bytes": required, "free_bytes": shutil.disk_usage(existing).free}
    if result["space"]["free_bytes"] < required:
        result["blockers"].append("发布文件准备空间不足")
    if not os.access(existing, os.W_OK | os.X_OK):
        result["blockers"].append("实例目录缺少写入或访问权限")


def inspect(instance, manifest, assets, lock, result):
    root = Path(instance["root"]).resolve()
    result["root"] = str(root)
    current = root / "current"
    if current.is_symlink():
        resolved = current.resolve()
        if resolved.parent != root / "releases" or not (resolved / "release.json").is_file():
            result["blockers"].append("current 未指向有效的本实例发布目录")
        else:
            previous = json.loads((resolved / "release.json").read_text())
            if previous["schema_version"] != 1 or previous["tool_version"] != 1:
                result["blockers"].append("当前发布清单版本不受支持")
            result["blockers"].extend(check_tree(resolved, previous["files"]))
            result["expected_current_release"] = previous["release_id"]
    else:
        result["first_takeover"] = True
        result["blockers"].append("首次接管：需声明目录调整、服务配置、环境处理和备份迁移方案")
    inspect_components(root, manifest, assets, result, instance)
    target = root / "environments" / manifest["environment"]["environment_id"]
    errors = check_environment(target, manifest["environment"], lock) if target.exists() else []
    result["components"]["environment"] = {
        "path": str(target),
        "action": "blocked" if errors else ("reuse" if target.exists() else "prepare"),
        "requirements": manifest["environment"],
        "problems": errors,
    }
    result["blockers"].extend(errors)
    inspect_config_and_space(root, manifest, result)


def plan(package, config, name, out):
    instance = load_instance(config, name)
    root = Path(instance["root"]).resolve()
    if out.resolve().is_relative_to(root) or out.resolve() in {package.resolve(), config.resolve()}:
        raise ValueError("计划输出必须位于实例外，且不能覆盖发布包或部署配置")
    result = {
        "schema_version": 2,
        "config_path": str(config.expanduser().resolve()),
        "package": str(package.resolve()),
        "plan_id": str(uuid.uuid4()),
        "instance": name,
        "service": instance["service"],
        "executable": False,
        "blockers": [],
        "components": {},
        "expected_current_release": None,
    }
    try:
        result["package_sha256"] = file_digest(package)
        manifest, assets, lock = read_package(package)
        result["target_release"] = manifest["release_id"]
        inspect(instance, manifest, assets, lock, result)
        result["freshness"] = freshness(instance, result)
        validate_urls(instance)
    except DeploymentError as error:
        result["blockers"].append(str(error))
    except (ValueError, OSError, KeyError, TypeError, tarfile.TarError) as error:
        result["blockers"].append(f"预检失败：{type(error).__name__}")
    result["executable"] = not result["blockers"]
    with os.fdopen(os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
        stream.write(json_bytes(result))
    return result
