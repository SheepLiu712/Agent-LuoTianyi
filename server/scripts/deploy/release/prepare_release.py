"""Online preparation in versioned locations, before stopping the current service."""

import json
import os
import shutil
import tarfile
import tempfile
from pathlib import Path

from cli import check_path
from deployment_state import DeploymentError, atomic_json
from plan import check_environment, check_tree, read_package
from release_contract import effective_config
from service_control import run


def prepare_release(package, root, manifest):
    target = root / "releases" / manifest["release_id"]
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".prepare-", dir=target.parent) as directory:
        temporary = Path(directory)
        read_package(package)
        with tarfile.open(package, "r:gz") as archive:
            for entry in archive:
                check_path(entry.name)
                if not entry.isfile():
                    raise DeploymentError("发布包包含非普通文件", 3)
                destination = temporary / entry.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("xb") as stream, archive.extractfile(entry) as source:
                    shutil.copyfileobj(source, stream)
                destination.chmod(0o755 if entry.mode & 0o111 else 0o644)
        if json.loads((temporary / "release.json").read_text()) != manifest:
            raise DeploymentError("解包清单与预检不一致", 3)
        errors = check_tree(temporary, manifest["files"])
        if errors:
            raise DeploymentError("解包后的发布文件校验失败")
        os.replace(temporary, target)
        # TemporaryDirectory cleanup tolerates its directory having been renamed.
    return target


def prepare_assets(root, manifest, assets, instance):
    target = root / "assets" / manifest["assets"]["version"]
    if target.exists():
        return target
    source = Path(instance["asset_source"])
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".prepare-", dir=target.parent) as directory:
        temporary = Path(directory)
        for entry in assets["files"]:
            destination = temporary / entry["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / entry["path"], destination)
        if check_tree(temporary, assets["files"]):
            raise DeploymentError("准备后的模型资产校验失败")
        os.replace(temporary, target)
    return target


def prepare_environment(root, release, manifest, lock):
    requirement = manifest["environment"]
    target = root / "environments" / requirement["environment_id"]
    if not target.exists():
        if not shutil.which("uv"):
            raise DeploymentError("准备 Python 环境需要安装 uv", 3)
        env = {**os.environ, "UV_PROJECT_ENVIRONMENT": str(target), "UV_LINK_MODE": "copy"}
        run(
            [
                "uv",
                "sync",
                "--project",
                str(release / "scripts/deploy/environment"),
                "--python",
                requirement["python_version"],
                "--locked",
                "--no-dev",
                "--no-install-project",
                "--no-install-package",
                "agentluo-server",
            ],
            timeout=3600,
            env=env,
        )
        browser_env = {**env, "PLAYWRIGHT_BROWSERS_PATH": str(target / "browsers")}
        run([str(target / "bin/python"), "-m", "playwright", "install", "chromium"], timeout=1800, env=browser_env)
        # Do not bind a reusable environment to an editable package in a particular release.
        atomic_json(target / "environment.json", requirement)
    errors = check_environment(target, requirement, lock)
    if errors:
        raise DeploymentError("; ".join(errors))
    return target


def check_startup(root, release, environment, assets, instance):
    """Use isolated config/data/runtime so preflight cannot initialize production writers."""
    with tempfile.TemporaryDirectory(prefix="preflight-", dir=root / "deployments") as directory:
        temporary = Path(directory)
        shutil.copytree(root / "config", temporary / "config")
        config = effective_config(json.loads((release / "config/config.json").read_text()), instance)
        atomic_json(temporary / "config/config.json", config)
        env = {
            **os.environ,
            "AGENTLUO_CONFIG_DIR": str(temporary / "config"),
            "AGENTLUO_DATA_DIR": str(temporary / "data"),
            "AGENTLUO_RUNTIME_DIR": str(temporary / "runtime"),
            "AGENTLUO_RESOURCE_DIR": str(release / "res"),
            "AGENTLUO_ASSET_DIR": str(assets),
            "PYTHONDONTWRITEBYTECODE": "1",
            "XDG_CACHE_HOME": str(temporary / "cache"),
            "PLAYWRIGHT_BROWSERS_PATH": str(environment / "browsers"),
        }
        run([str(environment / "bin/python"), str(release / "server_main.py"), "--check-startup"], timeout=120, env=env)
