from __future__ import annotations

import asyncio
import json
import random
import threading
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from src.utils.logger import get_logger
from src.world.bili_event_updater.cookie_manager import check_and_refresh_cookie
from src.world.get_new_songs.daily_new_song_fetcher import sync_daily_new_songs

if TYPE_CHECKING:
    from src.system.database.event_store import EventStore
    from src.world.citywalk.runtime_scheduler import CitywalkRuntimeService
    from src.world.get_new_songs.auto_song_learner import AutoSongLearner


class WorldDailyTasks:
    """Daily world maintenance actions registered independently on WorldClock."""

    def __init__(
        self,
        song_knowledge_config: Dict[str, Any],
        citywalk_service: Optional["CitywalkRuntimeService"],
        song_learner: Optional["AutoSongLearner"],
        event_store: Optional["EventStore"] = None,
        state_file: str = "data/world_clock/daily_state.json",
        citywalk_probability: float = 0.2,
        song_interval_days: int = 3,
        random_func: Optional[Callable[[], float]] = None,
    ) -> None:
        self.logger = get_logger(__name__)
        self.song_knowledge_config = song_knowledge_config
        self.citywalk_service = citywalk_service
        self.song_learner = song_learner
        self.event_store = event_store
        self.state_file = Path(state_file)
        self.citywalk_probability = citywalk_probability
        self.song_interval_days = song_interval_days
        self.random_func = random_func or random.random

    def purge_expired_events(self) -> None:
        if self.event_store is None:
            return
        try:
            self.event_store.purge_expired_events()
        except Exception as e:
            self.logger.warning(f"Expired event purge failed: {e}")

    def refresh_bili_cookie(self) -> None:
        try:
            check_and_refresh_cookie(force=False)
        except Exception as e:
            self.logger.warning(f"Cookie refresh task failed: {e}")

    def try_citywalk(self) -> None:
        if self.citywalk_service is None:
            self.logger.info("Citywalk service is not configured, skip daily citywalk")
            return
        if self.random_func() >= self.citywalk_probability:
            return

        def _target() -> None:
            try:
                overview = self.citywalk_service.run_once()
                if overview:
                    self._write_citywalk_event(overview)
            except Exception as exc:
                self.logger.error("Daily citywalk task failed: %s", exc)

        threading.Thread(target=_target, name="citywalk-runner", daemon=True).start()

    def sync_new_song_knowledge(self) -> None:
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        state = self._load_state()
        if not self.should_run_song_fetch(state.get("last_song_fetch_date", ""), now, self.song_interval_days):
            return

        def _target() -> None:
            try:
                result = sync_daily_new_songs(self.song_knowledge_config)
                self.logger.info(
                    "Daily song sync completed: added=%s failed=%s",
                    len(result.get("added", [])),
                    len(result.get("failed", [])),
                )
            except Exception as exc:
                self.logger.error("Daily song sync failed: %s", exc)

        threading.Thread(target=_target, name="daily-song-fetcher", daemon=True).start()
        state["last_song_fetch_date"] = today
        self._save_state(state)

    def learn_new_songs(self) -> None:
        if self.song_learner is None:
            return

        def _target() -> None:
            try:
                result = self.song_learner.try_learn_pending()
                self.logger.info(
                    "Daily song learner completed: learned=%s abandoned=%s awaiting=%s",
                    len(result.learned),
                    len(result.abandoned),
                    len(result.awaiting),
                )
                if result.learned:
                    self._write_new_song_event(result.learned)
            except Exception as exc:
                self.logger.error("Daily song learner failed: %s", exc)

        threading.Thread(target=_target, name="song-learner-runner", daemon=True).start()

    def check_qq_music_credential(self) -> None:
        if self.song_learner is None:
            return
        try:
            valid = self.song_learner.check_qq_credential()
            if valid:
                self.logger.info("QQ Music credential is valid")
            else:
                self.logger.warning("QQ Music credential is invalid; login QR has been generated")
        except Exception as e:
            self.logger.warning(f"QQ Music credential check failed: {e}")

    def _write_citywalk_event(self, overview: Any) -> None:
        if self.event_store is None:
            return
        try:
            normalized = self._normalize_citywalk_overview(overview)
            if not normalized:
                return
            date_str = normalized.get("date", "")
            dest = normalized.get("selected_destination") or normalized.get("selected_destination_name", "")
            title = f"Luo Tianyi visited {dest}" if dest else "Luo Tianyi citywalk"
            start_date = self._parse_date_or_today(date_str)
            asyncio.run(
                self.event_store.add_event(
                    {
                        "title": title,
                        "description": f"Luo Tianyi visited {dest} during an autonomous citywalk",
                        "event_type": "travel",
                        "start_datetime": start_date,
                        "is_recurring": False,
                        "is_personal": False,
                        "source": "citywalk",
                    }
                )
            )
        except Exception as e:
            self.logger.warning(f"Failed to write citywalk event: {e}")

    def _write_new_song_event(self, song_names: List[str]) -> None:
        if self.event_store is None:
            return
        try:
            display = ", ".join(song_names)
            asyncio.run(
                self.event_store.add_event(
                    {
                        "title": f"Luo Tianyi learned {display}",
                        "description": f"Luo Tianyi learned new song(s): {display}",
                        "event_type": "new_song",
                        "start_datetime": date.today(),
                        "is_recurring": False,
                        "is_personal": False,
                        "source": "song_learner",
                    }
                )
            )
        except Exception as e:
            self.logger.warning(f"Failed to write new song event: {e}")

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

    @staticmethod
    def _normalize_citywalk_overview(overview: Any) -> Optional[dict]:
        if isinstance(overview, dict):
            if isinstance(overview.get("overview"), dict):
                normalized = dict(overview["overview"])
                normalized.setdefault("date", str(overview.get("created_at", ""))[:10])
                return normalized
            return overview
        if isinstance(overview, str):
            path = Path(overview)
            if not path.exists():
                return None
            payload = json.loads(path.read_text(encoding="utf-8"))
            return WorldDailyTasks._normalize_citywalk_overview(payload)
        return None

    @staticmethod
    def _parse_date_or_today(raw: str) -> date:
        try:
            if raw:
                return datetime.strptime(raw[:10], "%Y-%m-%d").date()
        except Exception:
            pass
        return date.today()
