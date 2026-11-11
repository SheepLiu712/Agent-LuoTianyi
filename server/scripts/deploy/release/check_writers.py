#!/usr/bin/python3 -I
"""Root-owned, read-only /proc inspection for a single deployment root."""

import argparse
import os
from pathlib import Path


def references_instance(path, root):
    try:
        target = Path(os.readlink(path).removesuffix(" (deleted)"))
    except FileNotFoundError:
        return False
    if not target.is_absolute() or target == root / ".runtime/server.lock":
        return False
    return target.is_relative_to(root / "data") or target.is_relative_to(root / ".runtime")


def check(root, *, check_only=False, proc=Path("/proc")):
    for process in proc.iterdir():
        if not process.name.isdecimal() or int(process.name) == os.getpid():
            continue
        try:
            references = [process / "cwd", *(process / "fd").iterdir()]
            found = any(references_instance(path, root) for path in references)
            if found and not check_only:
                raise RuntimeError(f"Instance still has an accessing process: PID {process.name}")
        except (FileNotFoundError, ProcessLookupError):
            continue
        except PermissionError:
            raise RuntimeError(f"Cannot inspect process: PID {process.name}") from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    try:
        check(args.root.resolve(strict=True), check_only=args.check_only)
    except (RuntimeError, OSError) as error:
        print(str(error))
        return 3
    print("Process visibility verified" if args.check_only else "No instance accessing processes remain")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
