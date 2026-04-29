"""
Daily scheduler for plugins: handles citywalk and song fetcher scheduling at 4am every day.
"""

import json
import random
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from ..utils.logger import get_logger
from .music.daily_new_song_fetcher import sync_daily_new_songs


class DailyScheduler:
    """
    General-purpose daily scheduler for plugins.
    - Citywalk: 20% probability at 4am every day
    - Song fetcher: Every 3 days at 4am
    """

    def __init__(
        self,
        runtime_service: Any,
        state_file: str = "data/plugin_scheduler/scheduler_state.json",
        citywalk_probability: float = 0.2,
        song_interval_days: int = 3,
        random_func: Optional[Callable[[], float]] = None,
    ):
        self.logger = get_logger(__name__)
        self.runtime_service = runtime_service
        self.state_file = Path(state_file)
        self.citywalk_probability = citywalk_probability
        self.song_interval_days = song_interval_days
        self.random_func = random_func or random.random
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="daily-scheduler", daemon=True)
        self._thread.start()
        self.logger.info("日程调度器已启动（4am）")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        self.logger.info("日程调度器已停止")

    @staticmethod
    def should_run_song_fetch(last_run_date: str, current_date: datetime, interval_days: int) -> bool:
        if not last_run_date:
            return True
        try:
            last_date = datetime.strptime(last_run_date, "%Y-%m-%d").date()
        except Exception:
            return True
        return (current_date.date() - last_date).days >= interval_days

    def _load_state(self) -> Dict[str, str]:
        if not self.state_file.exists():
            return {}
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_state(self, state: Dict[str, str]) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _seconds_until_next_4am(self, now: datetime) -> float:
        next_run = now.replace(hour=4, minute=0, second=0, microsecond=0)
        if now >= next_run:
            next_run = next_run + timedelta(days=1)
        return max((next_run - now).total_seconds(), 1.0)

    def _run_citywalk_async(self) -> None:
        def _target():
            try:
                self.runtime_service.run_once()
            except Exception as exc:
                self.logger.error("凌晨城市漫步任务失败: %s", exc)

        threading.Thread(target=_target, name="citywalk-runner", daemon=True).start()

    def _run_song_fetch_async(self) -> None:
        def _target():
            try:
                result = sync_daily_new_songs(self.runtime_service.config_path)
                self.logger.info("凌晨歌曲同步完成: 新增=%s, 失败=%s", len(result.get("added", [])), len(result.get("failed", [])))
            except Exception as exc:
                self.logger.error("凌晨歌曲同步失败: %s", exc)

        threading.Thread(target=_target, name="daily-song-fetcher", daemon=True).start()

    def _run_once_for_day(self, now: datetime) -> None:
        today = now.strftime("%Y-%m-%d")
        state = self._load_state()
        if state.get("last_daily_check") == today:
            return

        if self.random_func() < self.citywalk_probability:
            self._run_citywalk_async()

        if self.should_run_song_fetch(state.get("last_song_fetch_date", ""), now, self.song_interval_days):
            self._run_song_fetch_async()
            state["last_song_fetch_date"] = today

        state["last_daily_check"] = today
        self._save_state(state)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            now = datetime.now()
            wait_seconds = self._seconds_until_next_4am(now)
            if self._stop_event.wait(timeout=wait_seconds):
                break
            self._run_once_for_day(datetime.now())
