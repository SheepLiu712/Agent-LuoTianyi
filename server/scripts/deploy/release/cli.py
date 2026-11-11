"""AgentLuo 服务端版本构建、部署计划、执行与状态查询。"""

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 的部署环境使用锁定的 tomli。
    import tomli as tomllib


from release_contract import CONFIG, MIGRATOR, SCHEMA, TEMPLATE, declarations

DEPLOY = "scripts/deploy/"
RESOURCES = DEPLOY + "release/resources.lock.json"
ASSETS = DEPLOY + "release/assets.lock.json"
LOCK = DEPLOY + "environment/uv.lock"
FIXED_FILES = {
    TEMPLATE,
    SCHEMA,
    MIGRATOR,
    DEPLOY + "release/release_contract.py",
    DEPLOY + "release/plan_database.py",
    "server_main.py",
    "pyproject.toml",
    "README.md",  # setuptools 构建 server 包时读取。
    DEPLOY + "deploy.py",
    DEPLOY + "README.md",
    DEPLOY + "RESOURCE_LAYOUT.md",
    DEPLOY + "release/cli.py",
    DEPLOY + "release/plan.py",
    DEPLOY + "release/apply.py",
    DEPLOY + "release/status.py",
    DEPLOY + "release/deployment_state.py",
    DEPLOY + "release/service_control.py",
    DEPLOY + "release/prepare_release.py",
    DEPLOY + "release/offline_steps.py",
    DEPLOY + "release/check_writers.py",
    DEPLOY + "release/probe_environment.py",
    DEPLOY + "startup/start_linux.sh",
    DEPLOY + "environment/install_linux.sh",
    DEPLOY + "release/check_resources.py",
    DEPLOY + "release/migrate_resource_layout.py",
    DEPLOY + "startup/agentluo.service.example",
    DEPLOY + "startup/agentluo-managed.service.example",
    DEPLOY + "startup/instance.env.example",
    DEPLOY + "environment/pyproject.toml",
    DEPLOY + "environment/.python-version",
    LOCK,
    RESOURCES,
    ASSETS,
}
RESOURCE_PREFIXES = (
    "res/admin_ui/admin_static/",
    "res/agent/persona/",
    "res/agent/prompts/",
    "res/agent/prepared_speech/",
    "src/world/",
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"


def git(*args, data=None):
    return subprocess.run(["git", *args], input=data, stdout=subprocess.PIPE, check=True).stdout


def tree_entries(commit):
    entries = {}
    for record in git("ls-tree", "--full-tree", "-rz", commit + ":server").split(b"\0"):
        if record:
            metadata, name = record.split(b"\t", 1)
            mode, _, oid = metadata.decode("ascii").split()
            entries[name.decode("utf-8")] = (mode, oid)
    return entries


def read_files(entries, paths):
    paths = sorted(paths)
    for path in paths:
        if path not in entries or entries[path][0] not in {"100644", "100755"}:
            raise ValueError(f"提交中缺少发布文件或文件类型不受支持：{path}")
    request = "".join(entries[path][1] + "\n" for path in paths).encode("ascii")
    stream = io.BytesIO(git("cat-file", "--batch", data=request))
    files = {}
    for path in paths:
        oid, kind, size = stream.readline().split()
        if kind != b"blob" or oid.decode("ascii") != entries[path][1]:
            raise ValueError(f"Git 对象与清单不符：{path}")
        files[path] = stream.read(int(size))
        if stream.read(1) != b"\n":
            raise ValueError(f"读取 Git 对象失败：{path}")
    return files


def check_path(path):
    relative = PurePosixPath(path)
    if relative.is_absolute() or relative.as_posix() != path or ".." in relative.parts or "\\" in path or ":" in path:
        raise ValueError(f"非法发布路径：{path}")


def locked_files(document, prefixes):
    if document["schema_version"] != 1 or not document["files"]:
        raise ValueError("资源清单为空或版本不受支持")
    result = {}
    for entry in document["files"]:
        path = entry["path"]
        check_path(path)
        if path in result or not path.startswith(prefixes):
            raise ValueError(f"资源清单路径重复或超出发布范围：{path}")
        if not re.fullmatch("[0-9a-f]{64}", entry["sha256"]) or not isinstance(entry["size"], int) or entry["size"] < 0:
            raise ValueError(f"无效的资源校验信息：{path}")
        result[path] = entry
    return result


def environment(files):
    lock = tomllib.loads(files[LOCK].decode("utf-8"))
    if lock["version"] != 1:
        raise ValueError("不支持的 uv.lock 版本")
    (torch,) = [package for package in lock["package"] if package["name"] == "torch"]
    requirements = {
        "python_version": files[DEPLOY + "environment/.python-version"].decode("ascii").strip(),
        "requires_python": lock["requires-python"],
        "platform": lock["supported-markers"],
        "torch_version": torch["version"],
        "torch_registry": torch["source"]["registry"],
        "dependency_lock": LOCK,
        "dependency_lock_sha256": digest(files[LOCK]),
    }
    return {**requirements, "environment_id": digest(json_bytes(requirements))}


def release(commit):
    entries = tree_entries(commit)
    files = read_files(entries, FIXED_FILES)
    resources = locked_files(json.loads(files[RESOURCES]), RESOURCE_PREFIXES)
    assets = json.loads(files[ASSETS])
    locked_files(assets, ("tts/", "song_learner/"))
    if not isinstance(assets["asset_version"], str) or not assets["asset_version"].strip():
        raise ValueError("模型资产缺少版本")
    sources = {path for path in entries if path.startswith("src/") and path.endswith(".py")}
    files.update(read_files(entries, sources | resources.keys()))
    files[CONFIG] = files[TEMPLATE]
    requirements = declarations(files)
    inventory = []
    for path, data in sorted(files.items()):
        check_path(path)
        entry = {"path": path, "size": len(data), "sha256": digest(data)}
        if path in resources and entry != resources[path]:
            raise ValueError(f"提交中的小资源与清单不一致：{path}")
        inventory.append(entry)
    manifest = {
        "schema_version": 1,
        "tool_version": 1,
        "commit_sha": commit,
        "files": inventory,
        "assets": {"version": assets["asset_version"], "lock": ASSETS, "lock_sha256": digest(files[ASSETS])},
        "environment": environment(files),
        **requirements,
    }
    manifest["release_id"] = "agentluo-" + commit
    files["release.json"] = json_bytes(manifest)
    return files, entries, manifest


def write_archive(stream, files, entries):
    with gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0, compresslevel=6) as compressed:
        with tarfile.open(fileobj=compressed, mode="w|") as archive:
            for path, data in sorted(files.items()):
                info = tarfile.TarInfo(path)
                info.size = len(data)
                info.mode = 0o755 if entries.get(path, (None,))[0] == "100755" else 0o644
                archive.addfile(info, io.BytesIO(data))


def file_digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def build(ref, output_dir):
    commit = git("rev-parse", "--verify", "--end-of-options", ref + "^{commit}").decode("ascii").strip()
    files, entries, manifest = release(commit)
    output_dir.mkdir(exist_ok=True, parents=True)
    package = output_dir.resolve() / (manifest["release_id"] + ".tar.gz")
    with tempfile.NamedTemporaryFile(dir=output_dir, delete=False) as stream:
        temporary = Path(stream.name)
    try:
        with temporary.open("wb") as stream:
            write_archive(stream, files, entries)
        checksum = file_digest(temporary)
        try:
            os.link(temporary, package)
        except FileExistsError:
            if file_digest(package) != checksum:
                raise ValueError(f"同名发布包已存在且内容不同：{package}") from None
    finally:
        temporary.unlink()
    return {
        "release_id": manifest["release_id"],
        "commit_sha": commit,
        "package": str(package),
        "package_sha256": checksum,
        "assets": manifest["assets"],
        "environment": manifest["environment"],
        "verified_files": len(manifest["files"]),
    }


def deployment_command(args):
    from deployment_state import DeploymentError

    try:
        if args.command == "apply":
            from apply import apply

            result, code = apply(args.plan, reuse_backup=args.reuse_backup)
        else:
            from status import status

            result, code = status(args.config, args.instance), 0
    except DeploymentError as error:
        result, code = {"error": str(error)}, error.code
    except (ValueError, OSError, KeyError, TypeError) as error:
        result, code = {"error": f"部署参数或记录错误：{type(error).__name__}"}, 2
    print(json.dumps(result, ensure_ascii=args.json, indent=None if args.json else 2))
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("~/.config/agentluo/deploy.toml"))
    commands = parser.add_subparsers(dest="command", required=True)
    builder = commands.add_parser("build", help="从指定提交构建发布包")
    builder.add_argument("--ref", required=True)
    builder.add_argument("--output-dir", type=Path, default=Path("dist"))
    builder.add_argument("--json", action="store_true")
    planner = commands.add_parser("plan", help="只读预检并输出部署计划")
    planner.add_argument("--package", type=Path, required=True)
    planner.add_argument("--instance", required=True)
    planner.add_argument("--out", type=Path, required=True)
    planner.add_argument("--json", action="store_true")
    executor = commands.add_parser("apply", help="执行已经生成的部署计划")
    executor.add_argument("--plan", type=Path, required=True)
    executor.add_argument("--json", action="store_true")
    executor.add_argument("--reuse-backup", type=Path, help="复用本实例已经验证的停服备份，避免重复复制")
    observer = commands.add_parser("status", help="查询实例实际状态和最近部署结果")
    observer.add_argument("--instance", required=True)
    observer.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.command in {"apply", "status"}:
        return deployment_command(args)
    if args.command == "plan":
        from plan import plan

        try:
            result = plan(args.package, args.config, args.instance, args.out)
        except (ValueError, OSError) as error:
            print(f"部署配置或计划输出错误：{type(error).__name__}", file=sys.stderr)
            return 2
        print(json.dumps(result, ensure_ascii=args.json, indent=None if args.json else 2))
        return 0 if result["executable"] else 3
    try:
        result = build(args.ref, args.output_dir)
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as error:
        print(f"构建失败：{error}", file=sys.stderr)
        return 5
    if args.json:
        print(json.dumps(result, ensure_ascii=True))
    else:
        print(f"发布包：{result['package']}\n提交：{result['commit_sha']}\nSHA-256：{result['package_sha256']}")
        print(f"已校验 {result['verified_files']} 个发布文件，资产版本：{result['assets']['version']}")
        print(f"环境：{result['environment']['environment_id']}，Python {result['environment']['python_version']}")


if __name__ == "__main__":
    sys.exit(main())
