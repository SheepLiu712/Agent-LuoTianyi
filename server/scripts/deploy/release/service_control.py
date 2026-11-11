"""Bounded systemd and HTTP operations. Never log credentials or endpoint bodies."""

import json
import os
import pwd
import shlex
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from deployment_state import DeploymentError

PROPERTIES = (
    "LoadState",
    "ActiveState",
    "SubState",
    "MainPID",
    "ExecStart",
    "WorkingDirectory",
    "EnvironmentFiles",
    "User",
    "KillMode",
    "ControlGroup",
    "NRestarts",
)


def run(command, *, timeout=120, env=None):
    try:
        result = subprocess.run(command, capture_output=True, timeout=timeout, env=env)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise DeploymentError(f"命令无法完成：{Path(command[0]).name} ({type(error).__name__})") from None
    if result.returncode:
        raise DeploymentError(f"命令失败：{shlex.join(command)}，退出码 {result.returncode}")
    return result.stdout.decode("utf-8", errors="replace")


class Systemd:
    def __init__(self, instance):
        self.instance = instance
        self.binary = shutil.which("systemctl") or "/usr/bin/systemctl"
        self.scope = instance.get("service_scope", "system")
        if self.scope not in {"system", "user"}:
            raise ValueError("service_scope 必须为 system 或 user")
        self.command = [self.binary] + (["--user"] if self.scope == "user" else [])
        self.control = self.command

    def query(self):
        output = run(
            self.command + ["show", self.instance["service"], "--property=" + ",".join(PROPERTIES)], timeout=15
        )
        return dict(line.split("=", 1) for line in output.splitlines() if "=" in line)

    def preflight(self, root):
        try:
            state = self.query()
        except DeploymentError:
            raise DeploymentError("无法读取 systemd 服务状态，拒绝执行部署", 3) from None
        launcher = str(root / "current/scripts/deploy/startup/start_linux.sh")
        environment = str(root / "deployments/instance.env")
        if (
            state.get("LoadState") != "loaded"
            or launcher not in state.get("ExecStart", "")
            or state.get("EnvironmentFiles", "") != f"{environment} (ignore_errors=no)"
            or state.get("WorkingDirectory") != str(root / "current")
            or state.get("KillMode") != "control-group"
        ):
            raise DeploymentError(
                "服务必须使用 managed systemd 模板，绑定本实例 current 与 deployments/instance.env", 3
            )
        user = state.get("User") or (pwd.getpwuid(os.getuid()).pw_name if self.scope == "user" else "root")
        if pwd.getpwnam(user).pw_uid != os.getuid():
            raise DeploymentError("请以 systemd 服务所属用户执行部署，避免写入其他用户的业务文件", 3)
        if self.scope == "system" and os.geteuid() != 0:
            self.control = ["sudo", "-n"] + self.command
            for action in ("stop", "start"):
                try:
                    run(
                        [
                            "sudo",
                            "-n",
                            "-l",
                            "--",
                            *self.command,
                            "--no-ask-password",
                            action,
                            self.instance["service"],
                        ],
                        timeout=15,
                    )
                except DeploymentError:
                    raise DeploymentError(
                        f"缺少非交互服务管理权限：systemctl {action} {self.instance['service']}", 3
                    ) from None
        return state

    def stop(self):
        run(self.control + ["--no-ask-password", "stop", self.instance["service"]], timeout=180)
        state = self.query()
        if state.get("ActiveState") not in {"inactive", "failed"} or state.get("MainPID") != "0":
            raise DeploymentError("服务未完全停止，拒绝迁移或切换")
        group = state.get("ControlGroup", "")
        if group:
            directory = Path("/sys/fs/cgroup") / group.lstrip("/")
            if any(p.read_text().strip() for p in directory.rglob("cgroup.procs")):
                raise DeploymentError("服务控制组仍存在进程，拒绝迁移")

    def start(self):
        run(self.control + ["--no-ask-password", "start", self.instance["service"]], timeout=180)


def actual_release(state, root):
    pid = state.get("MainPID", "0")
    if not pid.isdecimal() or pid == "0":
        return None
    try:
        args = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        for value in args:
            path = Path(os.fsdecode(value))
            if path.name == "server_main.py" and path.is_absolute():
                release = path.parent.resolve()
                if release.parent == root / "releases":
                    manifest = json.loads((release / "release.json").read_text())
                    if manifest.get("schema_version") == 1 and manifest.get("release_id") == release.name:
                        return manifest["release_id"]
    except (OSError, ValueError):
        pass
    return None


def process_bindings(state):
    """Expose only deployment path variables, never the rest of the process environment."""
    pid = state.get("MainPID", "0")
    if not pid.isdecimal() or pid == "0":
        return {}
    allowed = {
        "AGENTLUO_CONFIG_DIR",
        "AGENTLUO_DATA_DIR",
        "AGENTLUO_RUNTIME_DIR",
        "AGENTLUO_RESOURCE_DIR",
        "AGENTLUO_ASSET_DIR",
        "AGENTLUO_PYTHON",
        "PLAYWRIGHT_BROWSERS_PATH",
    }
    try:
        result = {}
        for entry in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0"):
            key, _, value = entry.partition(b"=")
            if os.fsdecode(key) in allowed:
                result[os.fsdecode(key)] = os.fsdecode(value)
        return result
    except OSError:
        return {}


def validate_urls(instance):
    for key in ("health_url", "admin_url"):
        parsed = urllib.parse.urlsplit(instance.get(key, ""))
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.username:
            raise DeploymentError(f"{key} 必须为本机无凭据 HTTP 地址", 3)
    if urllib.parse.urlsplit(instance["health_url"]).port != urllib.parse.urlsplit(instance["admin_url"]).port:
        raise DeploymentError("health_url 与 admin_url 必须指向相同端口", 3)
    if "is_debug" in instance and type(instance["is_debug"]) is not bool:
        raise DeploymentError("实例 is_debug 必须为布尔值", 3)
    timeout = instance.get("startup_timeout_seconds", 180)
    if type(timeout) is not int or not 1 <= timeout <= 3600:
        raise DeploymentError("startup_timeout_seconds 必须为 1 到 3600", 3)


def health(instance):
    result = {"healthy": False, "http_ok": False, "runtime_running": False, "admin_ok": False}
    try:
        validate_urls(instance)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(instance["health_url"], timeout=3) as response:
            document = json.loads(response.read(1024 * 1024))
            result["http_ok"] = response.status == 200 and isinstance(document, dict) and document.get("status") == "ok"
        if not isinstance(document, dict):
            return result
        runtime = document.get("runtime", {})
        if not isinstance(runtime, dict):
            return result
        result["runtime_running"] = (
            runtime.get("state") == "running" and runtime.get("running") is True and not runtime.get("error")
        )
        with opener.open(instance["admin_url"], timeout=3) as response:
            result["admin_ok"] = response.status == 200
        result["healthy"] = all(result[key] for key in ("http_ok", "runtime_running", "admin_ok"))
    except (OSError, ValueError, DeploymentError, urllib.error.URLError):
        pass
    return result


def await_healthy(controller, instance, release_id, expected_bindings):
    deadline = time.monotonic() + instance.get("startup_timeout_seconds", 180)
    root = Path(instance["root"]).resolve()
    initial = controller.query().get("NRestarts", "0")
    while time.monotonic() < deadline:
        state = controller.query()
        if state.get("NRestarts", "0") != initial:
            raise DeploymentError("启动验收期间服务发生重启")
        result = health(instance)
        if state.get("ActiveState") == "active" and actual_release(state, root) == release_id and result["healthy"]:
            if process_bindings(state) != expected_bindings:
                raise DeploymentError("运行进程的配置、数据、模型或 Python 路径与目标实例不一致")
            result["runtime_paths"] = expected_bindings
            return result
        time.sleep(1)
    raise DeploymentError("启动验收超时：服务、实际发布版本、运行时或管理页面未通过")
