"""Verify release resources; optional assets are checked only when explicitly requested."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def verify(root: Path, manifest: Path) -> list[str]:
    errors = []
    document = json.loads(manifest.read_text(encoding="utf-8"))
    if document.get("schema_version") != 1:
        raise ValueError("Unsupported resource manifest version")
    for entry in document["files"]:
        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"Invalid resource path: {relative}")
        path = root / relative
        if not path.is_file():
            errors.append(f"missing: {relative}")
            continue
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        if path.stat().st_size != entry["size"] or digest.hexdigest() != entry["sha256"]:
            errors.append(f"changed: {relative}")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--assets-root", type=Path)
    args = parser.parse_args()
    manifests = Path(__file__).resolve().parent
    errors = verify(args.server_root, manifests / "resources.lock.json")
    if args.assets_root:
        errors.extend(verify(args.assets_root, manifests / "assets.lock.json"))
    if errors:
        raise SystemExit("\n".join(errors))
    print("Release resources verified" + ("; external assets verified" if args.assets_root else ""))


if __name__ == "__main__":
    main()
