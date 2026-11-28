"""有所有权、时效和摘要的迁移文件；替换备份持久保留供用户恢复。"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from threading import RLock
from uuid import UUID, uuid4

from src.infrastructure.data_transfer._blob import (
    FileBlob,
    content_chunks,
    content_digest,
)


class TransferWorkspace:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._active = {}

    def put(self, kind, user_id, data, metadata=None):
        identity = str(uuid4())
        directory = self.root / kind / identity
        with self._lock:
            directory.mkdir(parents=True, mode=0o700)
            self._active[directory] = 1
        try:
            information = {
                **(metadata or {}),
                "user_id": user_id,
                "created_at": time.time(),
                "sha256": content_digest(data),
            }
            self._write(directory / "data.bin", data)
            self._write(directory / "info.json", json.dumps(information, ensure_ascii=False).encode("utf-8"))
            return identity
        finally:
            self._release(directory)

    def get(self, kind, identity, user_id):
        directory = self._directory(kind, identity)
        with self._lock:
            info = self._information(directory, kind, user_id)
            self._active[directory] = self._active.get(directory, 0) + 1
            data = FileBlob.open(directory / "data.bin", on_close=lambda: self._release(directory))
        try:
            if content_digest(data) != info["sha256"]:
                raise ValueError("TRANSFER_FILE_CHECKSUM_MISMATCH")
        except BaseException:
            data.close()
            raise
        return data, info

    def _information(self, directory, kind, user_id):
        try:
            info = json.loads((directory / "info.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise FileNotFoundError("TRANSFER_FILE_NOT_FOUND") from error
        if info.get("user_id") != user_id:
            raise FileNotFoundError("TRANSFER_FILE_NOT_FOUND")
        if kind == "previews" and time.time() - info["created_at"] > 3600 and not self._active.get(directory):
            raise FileNotFoundError("TRANSFER_PREVIEW_EXPIRED")
        return info

    def _release(self, directory):
        with self._lock:
            count = self._active[directory] - 1
            if count:
                self._active[directory] = count
            else:
                del self._active[directory]

    def cleanup_expired(self):
        """只回收过期且未被读取的预览；替换备份始终保留。"""
        previews = self.root / "previews"
        with self._lock:
            if not previews.exists():
                return
            for directory in previews.iterdir():
                if self._active.get(directory):
                    continue
                self._directory("previews", directory.name)
                if directory.is_symlink() or directory.resolve().parent != previews.resolve():
                    raise ValueError("TRANSFER_PREVIEW_UNSAFE_PATH")
                information = directory / "info.json"
                # 中途退出留下的不完整预览也按创建时间回收。
                created_at = (
                    json.loads(information.read_text(encoding="utf-8"))["created_at"]
                    if information.exists()
                    else directory.stat().st_mtime
                )
                if time.time() - created_at > 3600:
                    shutil.rmtree(directory)

    def save_result(self, identity, user_id, result):
        data, _ = self.get("previews", identity, user_id)
        try:
            directory = self._directory("previews", identity)
            self._write(directory / "result.json", json.dumps(result, ensure_ascii=False).encode("utf-8"))
        finally:
            data.close()

    def result(self, identity, user_id):
        data, _ = self.get("previews", identity, user_id)
        try:
            path = self._directory("previews", identity) / "result.json"
            return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        finally:
            data.close()

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
            for chunk in content_chunks(data):
                stream.write(chunk)
        os.replace(temporary, path)
