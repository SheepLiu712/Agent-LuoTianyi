"""
Daily scheduler for plugins: handles citywalk and song fetcher scheduling at 4am every day.
"""

import json
import random
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Optional
import asyncio
from src.utils.logger import get_logger
from src.world.get_new_songs.daily_new_song_fetcher import sync_daily_new_songs
from src.plugins.schedule.cookie_manager import check_and_refresh_cookie
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from src.world.citywalk.runtime_scheduler import CitywalkRuntimeService
    from src.world.get_new_songs.auto_song_learner import AutoSongLearner
    from src.plugins.schedule.schedule_manager import ScheduleManager



class DailyScheduler:
    """
    General-purpose daily scheduler for plugins.
    - Citywalk: 20% probability at 4am every day
    - Song fetcher: Every 3 days at 4am
    - Song learner: Every day at 4am
    - Event writing: Write citywalk/new_song events to EventStore
    """

    def __init__(
        self,
        song_knowledge_config: Dict[str, Any],
        citywalk_service: 'CitywalkRuntimeService',
        song_learner: 'AutoSongLearner',
        schedule_manager: Optional['ScheduleManager'] = None,
        state_file: str = "data/plugin_scheduler/scheduler_state.json",
        citywalk_probability: float = 0.2,
        song_interval_days: int = 3,
        random_func: Optional[Callable[[], float]] = None,
    ):
        self.logger = get_logger(__name__)
        self.song_knowledge_config = song_knowledge_config
        self.citywalk_service = citywalk_service
        self.state_file = Path(state_file)
        self.citywalk_probability = citywalk_probability
        self.song_interval_days = song_interval_days
        self.random_func = random_func or random.random
        self.song_learner: Optional['AutoSongLearner'] = song_learner
        self.schedule_manager: Optional['ScheduleManager'] = schedule_manager
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

    def _run_citywalk_async(self) -> None:
        def _target():
            try:
                overview = self.citywalk_service.run_once()
                if overview:
                    self._write_citywalk_event(overview)
            except Exception as exc:
                self.logger.error("凌晨城市漫步任务失败: %s", exc)

        threading.Thread(target=_target, name="citywalk-runner", daemon=True).start()

    def _run_song_fetch_async(self) -> None:
        def _target():
            try:
                result = sync_daily_new_songs(self.song_knowledge_config)
                self.logger.info("凌晨歌曲同步完成: 新增=%s, 失败=%s", len(result.get("added", [])), len(result.get("failed", [])))
            except Exception as exc:
                self.logger.error("凌晨歌曲同步失败: %s", exc)

        threading.Thread(target=_target, name="daily-song-fetcher", daemon=True).start()

    def _run_song_learner_async(self) -> None:
        if self.song_learner is None:
            return
        def _target():
            try:
                result = self.song_learner.try_learn_pending()
                self.logger.info(
                    "凌晨歌曲学习完成: 习得=%s, 放弃=%s, 等待=%s",
                    len(result.learned), len(result.abandoned), len(result.awaiting),
                )
                if result.learned:
                    self.logger.info("新学会的歌曲: %s", result.learned)
                    self._write_new_song_event(result.learned)
            except Exception as exc:
                self.logger.error("凌晨歌曲学习失败: %s", exc)
        threading.Thread(target=_target, name="song-learner-runner", daemon=True).start()

    def _write_citywalk_event(self, overview: dict) -> None:
        """将 citywalk 事件写入 EventStore。"""
        if not self.schedule_manager or not self.schedule_manager.event_store:
            return
        try:
            date_str = overview.get("date", "")
            dest = overview.get("selected_destination") or overview.get("selected_destination_name", "")
            title = f"洛天依在{dest}旅游" if dest else "洛天依旅游"
            from datetime import date
            if date_str:
                parts = date_str.split("-")
                start_date = date(int(parts[0]), int(parts[1]), int(parts[2]))
            else:
                start_date = date.today()
            asyncio.run(self.schedule_manager.event_store.add_event({
                "title": title,
                "description": f"洛天依独自前往{dest}游玩",
                "event_type": "travel",
                "start_datetime": start_date,
                "is_recurring": False,
                "is_personal": False,
                "source": "citywalk",
            }))
        except Exception as e:
            self.logger.warning(f"Failed to write citywalk event: {e}")

    def _write_new_song_event(self, song_names: List[str]) -> None:
        """将学会的新歌事件写入 EventStore。"""
        if not self.schedule_manager or not self.schedule_manager.event_store:
            return
        try:
            from datetime import date
            song_name_str = []
            for song_name in song_names:
                song_name_str.append(f"《{song_name}》")
            asyncio.run(
                self.schedule_manager.event_store.add_event({
                "title": f"洛天依学会了{', '.join(song_name_str)}",
                "description": f"洛天依学会了一首新歌{', '.join(song_name_str)}",
                "event_type": "new_song",
                "start_datetime": date.today(),
                "is_recurring": False,
                "is_personal": False,
                "source": "song_learner",
            }))
        except Exception as e:
            self.logger.warning(f"Failed to write new song event: {e}")

    def _run_once_for_day(self, now: datetime) -> None:
        '''
        每天4am执行一次，包含：
        - 过期事件清理（非周期、非用户事件）
        - B站 Cookie 刷新（检查过期，接近过期时自动更新）
        - 城市漫步（20%概率）
        - 歌曲同步（每3天一次）
        - 歌曲学习（每天一次，检查是否有待学歌曲）
        - 写入 citywalk / new_song 事件到 EventStore
        '''
        today = now.strftime("%Y-%m-%d")
        state = self._load_state()
        if state.get("last_daily_check") == today:
            return

        # 过期事件清理（凌晨先清理，再写入新事件）
        self._run_event_purge()

        # Cookie 刷新：每天检查一次，接近过期时自动用无头浏览器更新
        self._run_cookie_refresh()

        if self.random_func() < self.citywalk_probability:
            self._run_citywalk_async()

        if self.should_run_song_fetch(state.get("last_song_fetch_date", ""), now, self.song_interval_days):
            self._run_song_fetch_async()
            state["last_song_fetch_date"] = today

        # Song learner: runs every day at 4AM
        self._run_song_learner_async()

        # QQ 音乐凭证检查：每天凌晨复核，无效时生成二维码
        self._check_qq_music_credential()

        state["last_daily_check"] = today
        self._save_state(state)

    def _run_cookie_refresh(self) -> None:
        """检查 B站 Cookie 有效期，接近过期时自动刷新。"""
        try:
            check_and_refresh_cookie(force=False)
        except Exception as e:
            self.logger.warning(f"Cookie 刷新任务失败: {e}")

    def _check_qq_music_credential(self) -> None:
        """检查 QQ 音乐凭证有效性，无效时生成登录二维码。"""
        if self.song_learner is None:
            return
        try:
            valid = self.song_learner.check_qq_credential()
            if valid:
                self.logger.info("QQ 音乐凭证有效")
            else:
                self.logger.warning(
                    "QQ 音乐凭证无效，二维码已生成，请手动扫码登录"
                )
        except Exception as e:
            self.logger.warning(f"QQ 音乐凭证检查失败: {e}")

    def _run_event_purge(self) -> None:
        """清理过期的非周期事件。"""
        if not self.schedule_manager or not self.schedule_manager.event_store:
            return
        try:
            self.schedule_manager.event_store.purge_expired_events()
        except Exception as e:
            self.logger.warning(f"过期事件清理失败: {e}")

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            now = datetime.now()
            wait_seconds = self._seconds_until_next_4am(now)
            if self._stop_event.wait(timeout=wait_seconds):
                break
            self._run_once_for_day(datetime.now())

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
