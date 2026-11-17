"""Offline copy migration. Defaults to a plan; never deletes legacy resources."""

from __future__ import annotations

import argparse
import fcntl
import json
import shutil
import tempfile
from contextlib import ExitStack
from pathlib import Path

MOVES = (("res/sing_song", "data/singing"), ("res/knowledge", "data/knowledge"))


def rewrite_paths(value):
    if isinstance(value, dict):
        return {key: rewrite_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [rewrite_paths(item) for item in value]
    if isinstance(value, str):
        for old, new in MOVES:
            if value == old or value.startswith(old + "/"):
                return new + value[len(old) :]
    return value


def migrate(root: Path, *, apply: bool = False) -> list[str]:
    root = root.resolve()
    config_path = root / "config/config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    changes = [(root / old, root / new) for old, new in MOVES if (root / old).exists()]
    credential = root / "res/song_learner/.qq_music_credential.json"
    destination = root / "config/qq_music_credential.json"
    if credential.exists() and not destination.exists():
        changes.append((credential, destination))
    plan = [f"copy {src.relative_to(root)} -> {dst.relative_to(root)}" for src, dst in changes]
    plan.append("update config/config.json; preserve all source files")
    if not apply:
        return plan
    # The caller must stop all writers, including manual Python launches. Locks
    # coordinate with the supported installers and both production launchers.
    with ExitStack() as stack:
        runtime = root / ".runtime"
        runtime.mkdir(exist_ok=True)
        for name in ("server.lock", "production.lock"):
            lock = stack.enter_context((runtime / name).open("a"))
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        backup = config_path.with_name("config.before-resource-layout.json")
        if backup.exists():
            raise FileExistsError(f"Migration backup already exists: {backup}")
        for src, dst in changes:
            if dst.exists() or dst.is_symlink():
                raise FileExistsError(f"Refusing to overwrite {dst}")
            if src.is_symlink() or (src.is_dir() and any(p.is_symlink() for p in src.rglob("*"))):
                raise ValueError(f"Resolve linked resources manually before migration: {src}")
        shutil.copy2(config_path, backup)
        created = []
        try:
            for src, dst in changes:
                dst.parent.mkdir(parents=True, exist_ok=True)
                created.append(dst)
                if src.is_dir():
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
                    dst.chmod(0o600)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=config_path.parent, delete=False) as tmp:
                temp = Path(tmp.name)
                json.dump(rewrite_paths(config), tmp, ensure_ascii=False, indent=4)
                tmp.write("\n")
            try:
                temp.replace(config_path)
            finally:
                temp.unlink(missing_ok=True)
        except BaseException:
            for dst in reversed(created):
                if dst.is_dir():
                    shutil.rmtree(dst)
                else:
                    dst.unlink(missing_ok=True)
            backup.unlink(missing_ok=True)
            raise
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-root", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--offline", action="store_true", help="Confirm all service and maintenance writers are stopped"
    )
    args = parser.parse_args()
    if args.apply and not args.offline:
        parser.error("--apply requires --offline; stop all writers before copying databases")
    for line in migrate(args.server_root, apply=args.apply):
        print(line)


if __name__ == "__main__":
    main()
