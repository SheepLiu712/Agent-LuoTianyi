from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any


class SecretStore:
    """Local .env-backed secret store for runtime configuration."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def read(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        secrets: dict[str, str] = {}
        for raw_line in self.path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            secrets[key.strip()] = self._unquote(value.strip())
        return secrets

    def write(self, secrets: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            f"{key}={self._quote(value)}"
            for key, value in sorted(secrets.items())
            if key.strip()
        ]
        self._atomic_write("\n".join(lines) + ("\n" if lines else ""))

    def update(self, updates: dict[str, Any]) -> dict[str, str]:
        secrets = self.read()
        for key, value in updates.items():
            key = str(key).strip()
            if not key:
                continue
            if value is None or str(value) == "":
                secrets.pop(key, None)
            else:
                secrets[key] = str(value)
        self.write(secrets)
        self.load_into_environment()
        return secrets

    def load_into_environment(self) -> dict[str, str]:
        secrets = self.read()
        for key, value in secrets.items():
            os.environ[key] = value
        return secrets

    def status(self, keys: list[str] | None = None) -> dict[str, dict[str, Any]]:
        secrets = self.read()
        names = keys or sorted(secrets)
        return {
            key: {
                "configured": bool(secrets.get(key) or os.environ.get(key)),
                "source": "secret_store" if key in secrets else ("environment" if os.environ.get(key) else None),
                "masked": self.mask(secrets.get(key) or os.environ.get(key) or ""),
            }
            for key in names
        }

    @staticmethod
    def mask(value: str) -> str:
        if not value:
            return ""
        if len(value) <= 8:
            return "*" * len(value)
        return f"{value[:3]}{'*' * 6}{value[-3:]}"

    @staticmethod
    def _quote(value: str) -> str:
        if any(ch in value for ch in "\n\r"):
            value = value.replace("\r", "").replace("\n", "\\n")
        if not value or any(ch.isspace() for ch in value) or value.startswith(("#", '"', "'")):
            return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
        return value

    @staticmethod
    def _unquote(value: str) -> str:
        if len(value) >= 2 and value[0] == value[-1] == '"':
            return value[1:-1].replace('\\"', '"').replace("\\\\", "\\").replace("\\n", "\n")
        if len(value) >= 2 and value[0] == value[-1] == "'":
            return value[1:-1]
        return value

    def _atomic_write(self, content: str) -> None:
        fd, tmp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=str(self.path.parent), text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)
            os.replace(tmp_name, self.path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
