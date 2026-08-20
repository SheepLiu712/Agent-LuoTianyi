from __future__ import annotations

from typing import Any, Dict, Iterable, TYPE_CHECKING

from src.world.types.task_result import WorldTaskResult
from src.world.types.world_task import WorldTask

if TYPE_CHECKING:
    from src.system.system_runtime import SystemRuntime
    from src.world.learn_sing_songs.task import LearnSingSongsTask


class QQMusicCredentialRefreshTask(WorldTask):
    """Periodically keep every distinct QQ Music credential ready for song learning."""

    base_task_name = "qq_music_credential_refresh"

    def __init__(
        self,
        learn_sing_songs_tasks: Iterable["LearnSingSongsTask"],
        config: Dict[str, Any] | None = None,
    ) -> None:
        task_config = dict(config or {})
        clock_config = dict(task_config.get("clock_config") or {})
        clock_params = {
            "interval_seconds": 21600,
            "run_immediately": True,
            **dict(clock_config.get("params") or {}),
        }
        task_config["clock_config"] = {
            "type": clock_config.get("type", "interval"),
            "params": clock_params,
        }

        super().__init__(self.base_task_name, task_config)
        self.learn_sing_songs_tasks = list(learn_sing_songs_tasks)
        self.system_runtime: "SystemRuntime | None" = None

    def initialize(self, system_runtime: "SystemRuntime") -> None:
        self.system_runtime = system_runtime

    def ensure_dependencies(self) -> None:
        super().ensure_dependencies()
        if self.system_runtime is None:
            raise RuntimeError("QQMusicCredentialRefreshTask dependency is missing: system_runtime")
        if not self.learn_sing_songs_tasks:
            raise RuntimeError("QQMusicCredentialRefreshTask dependency is missing: learn_sing_songs_tasks")

    def run_once(self) -> WorldTaskResult:
        checked_files: set[str] = set()
        failed_characters: list[str] = []

        for learn_task in self.learn_sing_songs_tasks:
            learner = getattr(learn_task, "auto_song_learner", None)
            credential_file = getattr(learner, "_credential_file", None)
            if credential_file is None:
                continue

            credential_key = str(credential_file.resolve()).casefold()
            if credential_key in checked_files:
                continue
            checked_files.add(credential_key)

            if not learner.check_qq_credential():
                failed_characters.append(str(getattr(learn_task, "character_id", "unknown")))

        if not checked_files:
            return WorldTaskResult.skipped_result(
                self.task_name,
                "no initialized QQ Music credential is available",
                credential_count=0,
            )
        if failed_characters:
            return WorldTaskResult.failure(
                self.task_name,
                "one or more QQ Music credentials could not be refreshed",
                credential_count=len(checked_files),
                failed_characters=failed_characters,
            )
        return WorldTaskResult.success(
            self.task_name,
            "QQ Music credentials are ready",
            credential_count=len(checked_files),
        )
