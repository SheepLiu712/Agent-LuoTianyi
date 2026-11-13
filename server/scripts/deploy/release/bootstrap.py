"""Prepare a new Linux instance without exposing its internal directory layout."""

import argparse
import json
import os
import pwd
import re
import secrets
import subprocess
from pathlib import Path

from cli import ASSETS, build, git, locked_files
from deployment_state import DeploymentError, atomic_bytes, atomic_json, ensure_local_layout, load_instance
from offline_steps import runtime_lock, switch
from plan import check_tree, read_package
from prepare_release import check_startup, prepare_assets, prepare_environment, prepare_release

DIRECTORIES = ("releases", "assets", "environments", "config", "data", ".runtime", "deployments")


def instance_root(value):
    path = Path(value).expanduser()
    if not path.is_absolute() or not re.fullmatch(r"/[A-Za-z0-9_./-]+", str(path)):
        raise ValueError("实例位置须为绝对路径，仅支持字母、数字、下划线、点、横线和斜杠")
    if path.is_symlink() or path.resolve() != path:
        raise ValueError("实例位置不能包含符号链接或 ..")
    return path


def settings(root):
    ensure_local_layout(root)
    if (root / "assets").is_symlink():
        raise ValueError("assets 不能是符号链接")
    record = json.loads((root / "deployments/bootstrap.json").read_text())
    if record.get("root") != str(root) or record.get("owner") != os.getuid():
        raise ValueError("请使用初始化实例的账号和目录执行")
    for name in DIRECTORIES:
        if not (root / name).is_dir():
            raise ValueError(f"实例目录缺失：{name}")
    instance = load_instance(root / "deployments/deploy.toml", record["name"])
    if instance["root"] != str(root):
        raise ValueError("部署配置中的实例位置已改变")
    return record, instance


def initialize(root, name, port):
    if (name is not None and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", name)) or not 1024 <= port <= 65535:
        raise ValueError("名称须以字母开头且仅含字母、数字、横线或下划线；端口范围 1024–65535")
    if root.exists() and any(root.iterdir()):
        raise ValueError("实例目录非空；请选择新的空目录。已有实例无需重新初始化")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    for directory in DIRECTORIES:
        (root / directory).mkdir(mode=0o700)
    service_name = f"agentluo-{name}.service" if name else "agentluo.service"
    instance_name = name if name is not None else "production"
    instance = (
        f'[instances.{instance_name}]\nroot = "{root}"\nservice = "{service_name}"\n'
        'service_scope = "system"\nis_debug = false\nstartup_timeout_seconds = 180\n'
        f'health_url = "http://127.0.0.1:{port}/admin/api/health"\n'
        f'admin_url = "http://127.0.0.1:{port}/admin"\n'
    )
    atomic_bytes(root / "deployments/deploy.toml", instance.encode())
    atomic_bytes(
        root / "config/secrets.local.env",
        (f"JWT_SECRET={secrets.token_urlsafe(48)}\nQWEN_API_KEY=\nSILICONFLOW_API_KEY=\nAMAP_KEY=\n").encode(),
    )
    atomic_json(root / "deployments/bootstrap.json", {"root": str(root), "owner": os.getuid(), "name": instance_name})
    return {
        "message": "目录已创建；请填写密钥文件中的 API 密钥",
        "secrets_file": str(root / "config/secrets.local.env"),
    }


def verify_tree(root, entries):
    # Never chmod through links, including links to another path within the same tree.
    for entry in entries:
        path = root / entry["path"]
        for candidate in (path, *path.parents):
            if candidate.is_symlink():
                raise ValueError(f"资产或发布目录包含符号链接：{candidate}")
            if candidate == root:
                break
    errors = check_tree(root, entries)
    if errors:
        raise ValueError("\n".join(errors))


def private_assets(target, entries):
    verify_tree(target, entries)
    paths = {target}
    for entry in entries:
        path = target / entry["path"]
        paths.add(path)
        paths.update(parent for parent in path.parents if parent.is_relative_to(target))
    for path in paths:
        if path.stat().st_uid != os.getuid():
            raise ValueError(f"资产不属于当前账号，无法配置权限：{path}")
    for path in paths:
        path.chmod(path.stat().st_mode & 0o777 & ~0o022)


def install_assets(root, source, ref):
    settings(root)
    document = json.loads(git("show", f"{ref}:server/{ASSETS}"))
    locked_files(document, ("tts/", "song_learner/"))
    version = document["asset_version"]
    if not re.fullmatch(r"[A-Za-z0-9_-]+", version):
        raise ValueError("资产版本标识无效")
    source = Path(source).absolute()
    verify_tree(source, document["files"])
    from apply import deployment_lock

    with deployment_lock(root):
        target = root / "assets" / version
        if target.exists():
            verify_tree(target, document["files"])
        target = prepare_assets(root, {"assets": {"version": version}}, document, {"asset_source": str(source)})
        private_assets(target, document["files"])
    return {"message": "资产校验和权限配置完成；源目录未修改", "assets": str(target), "files": len(document["files"])}


def require_fresh(root):
    if (root / "current").exists() or (root / "current").is_symlink():
        raise ValueError("实例已部署；更新版本请使用 plan/apply，不能重复首次安装")
    if any((root / "data").iterdir()):
        raise ValueError("实例已有数据，首次安装不会接管或覆盖旧数据")
    if (root / "config/config.json").exists():
        raise ValueError("实例已有普通配置，请检查是否有未完成的安装；不会覆盖")


def install(root, ref):
    _, instance = settings(root)
    from apply import deployment_lock

    with deployment_lock(root), runtime_lock(root):
        require_fresh(root)
        built = build(ref, root / "deployments/packages")
        package = Path(built["package"])
        manifest, assets, lock = read_package(package)
        asset_dir = root / "assets" / assets["asset_version"]
        private_assets(asset_dir, assets["files"])
        release = root / "releases" / manifest["release_id"]
        if release.exists():
            verify_tree(release, manifest["files"])
            if json.loads((release / "release.json").read_text()) != manifest:
                raise ValueError("已有发布清单不匹配")
        release = prepare_release(package, root, manifest)
        environment = root / "environments" / manifest["environment"]["environment_id"]
        if environment.is_symlink():
            raise ValueError("环境目录不能是符号链接")
        environment = prepare_environment(root, release, manifest, lock)
        check_startup(root, release, environment, asset_dir, instance)
        switch(root, release, environment, asset_dir, instance)
    return {
        "message": "首次部署文件已就绪；下一步执行 systemd 安装并启动服务，数据库将在服务启动时初始化",
        "release_id": manifest["release_id"],
        "admin_url": instance["admin_url"],
    }


def service_file(root):
    _, instance = settings(root)
    release = (root / "current").resolve()
    if release.parent != root / "releases" or not (release / "release.json").is_file():
        raise ValueError("请先执行 install 完成首次部署")
    if not (root / "deployments/instance.env").is_file():
        raise ValueError("实例启动配置缺失，请检查首次部署结果")
    user = pwd.getpwuid(os.getuid()).pw_name
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", user):
        raise ValueError("服务账号名称不受支持")
    template = Path(__file__).resolve().parent.parent / "startup/agentluo-managed.service.example"
    content = template.read_text().replace("@INSTANCE_ROOT@", str(root)).replace("@SERVICE_USER@", user)
    return instance, content


def install_service(root, *, unit_directory=Path("/etc/systemd/system")):
    from apply import deployment_lock

    with deployment_lock(root):
        instance, content = service_file(root)
        name = instance["service"]
        destination = unit_directory / name
        if destination.is_symlink() or (destination.exists() and destination.read_text() != content):
            raise ValueError(f"已有不同的服务单元，不会覆盖：{destination}")
        query = subprocess.run(
            ["systemctl", "show", name, "--property=LoadState,FragmentPath"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        state = dict(line.split("=", 1) for line in query.stdout.splitlines() if "=" in line)
        if state.get("LoadState") not in {"loaded", "not-found"}:
            raise ValueError("无法确认 systemd 单元状态，请确认主机由 systemd 管理")
        fragment = state.get("FragmentPath", "")
        if fragment and fragment != str(destination):
            raise ValueError(f"已有其他位置的同名服务，不会覆盖：{fragment}")
        unit = root / "deployments" / name
        atomic_bytes(unit, content.encode())
        subprocess.run(["systemd-analyze", "verify", str(unit)], check=True)
        subprocess.run(["sudo", "install", "-m", "644", str(unit), str(destination)], check=True)
        subprocess.run(["sudo", "systemctl", "daemon-reload"], check=True)
        subprocess.run(["sudo", "systemctl", "enable", "--now", name], check=True)
        subprocess.run(["systemctl", "is-active", "--quiet", name], check=True)
    return {
        "message": "systemd 服务已启动并设置开机自启；请打开管理页面确认业务运行时状态",
        "service": name,
        "admin_url": instance["admin_url"],
        "logs": f"journalctl -u {name} -n 100 --no-pager",
    }


def execute(args):
    try:
        if os.getuid() == 0:
            raise ValueError("请以普通服务账号执行；安装 systemd 时脚本会单独调用 sudo")
        root = instance_root(args.root)
        if args.command == "init":
            result = initialize(root, args.name, args.port)
        elif args.command == "assets":
            result = install_assets(root, args.source, args.ref)
        elif args.command == "install":
            result = install(root, args.ref)
        else:
            result = install_service(root)
    except (ValueError, OSError, KeyError, DeploymentError, subprocess.SubprocessError) as error:
        print(f"首次部署失败：{error}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main():
    parser = argparse.ArgumentParser(description="Linux 首次实例准备（由 shell 入口调用）")
    commands = parser.add_subparsers(dest="command", required=True)
    initializer = commands.add_parser("init", help="在空目录创建新实例和密钥文件")
    initializer.add_argument("--root", required=True)
    initializer.add_argument(
        "--name", help="服务名后缀，例如 test 生成 agentluo-test.service；省略时为 agentluo.service"
    )
    initializer.add_argument("--port", type=int, default=15673)
    installer = commands.add_parser("install", help="从 Git 提交完成新实例的首次部署")
    installer.add_argument("--root", required=True)
    installer.add_argument("--ref", default="HEAD")
    return execute(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
