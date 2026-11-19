"""有所有权、时效和摘要的迁移文件；替换备份持久保留供用户恢复。"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from uuid import UUID, uuid4


class TransferWorkspace:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, kind, user_id, data, metadata=None):
        identity = str(uuid4())
        directory = self.root / kind / identity
        directory.mkdir(parents=True, mode=0o700)
        information = {
            **(metadata or {}),
            "user_id": user_id,
            "created_at": time.time(),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        self._write(directory / "data.bin", data)
        self._write(directory / "info.json", json.dumps(information, ensure_ascii=False).encode("utf-8"))
        return identity

    def get(self, kind, identity, user_id):
        directory = self._directory(kind, identity)
        try:
            info = json.loads((directory / "info.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise FileNotFoundError("TRANSFER_FILE_NOT_FOUND") from error
        if info.get("user_id") != user_id:
            raise FileNotFoundError("TRANSFER_FILE_NOT_FOUND")
        if kind == "previews" and time.time() - info["created_at"] > 3600:
            raise FileNotFoundError("TRANSFER_PREVIEW_EXPIRED")
        data = (directory / "data.bin").read_bytes()
        if hashlib.sha256(data).hexdigest() != info["sha256"]:
            raise ValueError("TRANSFER_FILE_CHECKSUM_MISMATCH")
        return data, info

    def save_result(self, identity, user_id, result):
        directory = self._directory("previews", identity)
        self.get("previews", identity, user_id)
        self._write(directory / "result.json", json.dumps(result, ensure_ascii=False).encode("utf-8"))

    def result(self, identity, user_id):
        self.get("previews", identity, user_id)
        path = self._directory("previews", identity) / "result.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def _directory(self, kind, identity):
        try:
            if str(UUID(identity)) != identity:
                raise ValueError("non-canonical UUID")
        except (ValueError, TypeError, AttributeError) as error:
            raise FileNotFoundError("TRANSFER_FILE_NOT_FOUND") from error
        return self.root / kind / identity

    @staticmethod
    def _write(path, data):
        temporary = path.with_suffix(".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        os.replace(temporary, path)
