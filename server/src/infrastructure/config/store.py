from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from src.utils.helpers import apply_env_variables


class ConfigStore:
    """UTF-8 JSON config store with backup and env resolution helpers."""

    def __init__(self, path: str | Path, *, root_dir: str | Path) -> None:
        self.path = Path(path)
        self.root_dir = Path(root_dir)

    def read_raw(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        with self.path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def read_resolved(self) -> dict[str, Any]:
        return apply_env_variables(self.read_raw())

    def write_raw(self, config: dict[str, Any], *, backup: bool = True) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if backup and self.path.exists():
            backup_dir = self.path.parent / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            shutil.copy2(self.path, backup_dir / f"{self.path.stem}.{stamp}{self.path.suffix}")

        content = json.dumps(config, ensure_ascii=False, indent=4) + "\n"
        fd, tmp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=str(self.path.parent), text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)
            os.replace(tmp_name, self.path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    def resolve_path(self, raw_path: str | Path) -> Path:
        path = Path(raw_path)
        if path.is_absolute():
            return path
        return self.root_dir / path
