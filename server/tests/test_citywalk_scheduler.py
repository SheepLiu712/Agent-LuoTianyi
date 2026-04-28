import json
from datetime import datetime

from src.plugins import DailyScheduler


class DummyRuntime:
    config_path = "config/config.json"

    def run_once(self):
        return "ok"


class SchedulerProbe(DailyScheduler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.citywalk_called = 0
        self.song_called = 0

    def _run_citywalk_async(self):
        self.citywalk_called += 1

    def _run_song_fetch_async(self):
        self.song_called += 1


def test_should_run_song_fetch_every_3_days():
    now = datetime(2026, 4, 27, 1, 0, 0)
    assert DailyScheduler.should_run_song_fetch("", now, 3)
    assert not DailyScheduler.should_run_song_fetch("2026-04-26", now, 3)
    assert DailyScheduler.should_run_song_fetch("2026-04-24", now, 3)


def test_scheduler_run_once_for_day(tmp_path):
    state_file = tmp_path / "scheduler_state.json"
    scheduler = SchedulerProbe(
        runtime_service=DummyRuntime(),
        state_file=str(state_file),
        citywalk_probability=0.2,
        song_interval_days=3,
        random_func=lambda: 0.1,
    )

    scheduler._run_once_for_day(datetime(2026, 4, 27, 1, 0, 0))
    assert scheduler.citywalk_called == 1
    assert scheduler.song_called == 1

    # 同一天再次执行应被状态文件拦截
    scheduler._run_once_for_day(datetime(2026, 4, 27, 1, 10, 0))
    assert scheduler.citywalk_called == 1
    assert scheduler.song_called == 1

    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state["last_daily_check"] == "2026-04-27"
    assert state["last_song_fetch_date"] == "2026-04-27"
