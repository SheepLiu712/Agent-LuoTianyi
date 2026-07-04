from __future__ import annotations

import json
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.system.admin.config_store import ConfigStore
from src.utils.logger import get_logger
from src.world.learn_sing_songs.song_learner.src.pipeline import download_qq_song


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class QQMusicCredentialRefreshService:
    """Runs QQ Music credential refresh in a single background thread."""

    def __init__(
        self,
        *,
        root_dir: str | Path,
        config_store: ConfigStore,
        runtime_getter: Callable[[], Any | None] | None = None,
    ) -> None:
        self.root_dir = Path(root_dir)
        self.config_store = config_store
        self.runtime_getter = runtime_getter
        self.logger = get_logger("QQMusicCredentialRefresh")
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._status: dict[str, Any] = {
            "state": "idle",
            "running": False,
            "message": "尚未刷新 QQ 音乐凭证",
            "started_at": None,
            "finished_at": None,
            "success": None,
            "credential_file": None,
            "legacy_file": None,
            "qr_file": None,
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._status)

    def start(self, *, timeout_seconds: int = 30) -> dict[str, Any]:
        with self._lock:
            if self._status.get("running"):
                return dict(self._status)
            credential_file, legacy_file = self._resolve_credential_paths()
            qr_file = credential_file.parent / "qq_login_qr.png"
            self._status = {
                "state": "running",
                "running": True,
                "message": f"正在更新 QQ 音乐凭证，二维码将生成到 {qr_file}",
                "started_at": _utc_now_iso(),
                "finished_at": None,
                "success": None,
                "credential_file": str(credential_file),
                "legacy_file": str(legacy_file),
                "qr_file": str(qr_file),
            }
            self._thread = threading.Thread(
                target=self._run_refresh,
                args=(credential_file, legacy_file, timeout_seconds),
                name="qq-music-credential-refresh",
                daemon=True,
            )
            self._thread.start()
            return dict(self._status)

    def qr_file(self) -> Path | None:
        with self._lock:
            raw_path = self._status.get("qr_file")
        if not raw_path:
            return None
        return Path(str(raw_path))

    def _run_refresh(self, credential_file: Path, legacy_file: Path, timeout_seconds: int) -> None:
        try:
            if not download_qq_song.QQ_SDK_AVAILABLE:
                raise RuntimeError(f"qqmusic-api-python 不可用: {download_qq_song.QQ_SDK_IMPORT_ERROR}")

            download_qq_song.ensure_qr_login(
                credential_file=credential_file,
                login_timeout=timeout_seconds,
                force_login=True,
            )
            saved = download_qq_song.load_saved_credential(credential_file)
            if not saved or not download_qq_song.validate_credential(saved):
                raise RuntimeError(f"登录完成但 credential 格式校验失败: {credential_file}")

            if credential_file.resolve() != legacy_file.resolve():
                legacy_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(credential_file, legacy_file)

            self._mark_runtime_credentials_valid(credential_file)
            self._finish(True, f"QQ 音乐凭证刷新成功: {credential_file}")
        except Exception as exc:
            self.logger.warning(f"QQ 音乐凭证刷新失败: {exc}")
            self._finish(False, f"QQ 音乐凭证刷新失败: {exc}")

    def _finish(self, success: bool, message: str) -> None:
        with self._lock:
            self._status.update(
                {
                    "state": "success" if success else "failed",
                    "running": False,
                    "message": message,
                    "finished_at": _utc_now_iso(),
                    "success": success,
                }
            )

    def _resolve_credential_paths(self) -> tuple[Path, Path]:
        raw_config = self._read_raw_config_safely()
        learner_cfg = (raw_config.get("world") or {}).get("auto_song_learner") or {}
        credential_file = self._resolve_path(learner_cfg.get("qq_credential_file") or "config/qq_music_credential.json")
        resource_dir = self._resolve_path(learner_cfg.get("songlearner_resource_dir") or "res/song_learner")
        return credential_file, resource_dir / ".qq_music_credential.json"

    def _read_raw_config_safely(self) -> dict[str, Any]:
        try:
            return self.config_store.read_raw()
        except (json.JSONDecodeError, OSError) as exc:
            self.logger.warning(f"读取配置失败，使用默认 QQ 音乐凭证路径: {exc}")
            return {}

    def _resolve_path(self, raw_path: str | Path) -> Path:
        path = Path(raw_path).expanduser()
        if path.is_absolute():
            return path
        return self.root_dir / path

    def _mark_runtime_credentials_valid(self, credential_file: Path) -> None:
        if self.runtime_getter is None:
            return
        runtime = self.runtime_getter()
        world_runtime = getattr(runtime, "world", None)
        tasks = getattr(world_runtime, "learn_sing_songs_tasks", []) or []
        for task in tasks:
            learner = getattr(task, "auto_song_learner", None)
            if learner is None:
                continue
            learner_file = getattr(learner, "_credential_file", None)
            if learner_file is not None and Path(learner_file).resolve() != credential_file.resolve():
                continue
            setattr(learner, "qq_credential_valid", True)
