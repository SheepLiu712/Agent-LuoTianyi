import json
import threading
from types import SimpleNamespace

import pytest

import src.world.bili_event_updater.task as task_module
from src.infrastructure.persistence.database.event_models import UnifiedEventType
from src.world.bili_event_updater.official_feed_fetcher import OfficialFeedFetcher
from src.world.bili_event_updater.task import BiliEventUpdateTask
from src.world.bili_event_updater.types import OfficialDynamic
from src.world.bili_event_updater.updater import BiliEventUpdater


def test_bili_event_update_initialize_builds_updater(monkeypatch):
    captured = {}

    class FakeUpdater:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    class FakeLLMService:
        def register_llm_module(self, name, config):
            return ("llm", name, config)

        def register_vlm_module(self, name, config):
            return ("vlm", name, config)

    monkeypatch.setattr(task_module, "BiliEventUpdater", FakeUpdater)
    event_store = object()
    runtime = SimpleNamespace(
        database_manager=SimpleNamespace(event_store=event_store),
        llm_service=FakeLLMService(),
    )
    cfg = {"fetch_interval_hours": 2, "llm_module": {"a": 1}, "vlm_module": {"b": 2}}
    task = BiliEventUpdateTask(cfg)

    task.initialize(runtime)

    assert captured["config"] is cfg
    assert captured["event_store"] is event_store
    assert captured["llm_module"][0] == "llm"
    assert captured["llm_module"][1] == "luotianyi_bili_event_parser"
    assert captured["vlm_module"][0] == "vlm"
    assert captured["vlm_module"][1] == "luotianyi_bili_event_parser"
    assert task.get_task_type() == "interval"


def test_official_feed_fetcher_save_cache_merges_existing_character_cache(tmp_path):
    cache_file = tmp_path / "feed_cache.json"
    cache_file.write_text(
        json.dumps({"luotianyi": ["old-1", "old-2"]}, ensure_ascii=False),
        encoding="utf-8",
    )
    fetcher = OfficialFeedFetcher(
        {
            "data_file": str(cache_file),
            "bilibili_uids": {"miku": "123"},
        }
    )
    fetcher.seen_ids = {"miku": ["new-1"]}

    fetcher._save_cache()

    saved = json.loads(cache_file.read_text(encoding="utf-8"))
    assert saved["luotianyi"] == ["old-1", "old-2"]
    assert saved["miku"] == ["new-1"]


def test_official_feed_fetcher_marks_ids_only_after_processing(tmp_path, monkeypatch):
    cache_file = tmp_path / "feed_cache.json"
    fetcher = OfficialFeedFetcher({"data_file": str(cache_file), "bilibili_uids": {"luotianyi": "36081646"}})
    item = OfficialDynamic(
        uid="36081646",
        account_name="洛天依",
        character="luotianyi",
        platform="bilibili",
        dynamic_id="new-1",
        dynamic_type="DYNAMIC_TYPE_WORD",
        content="hello",
        raw_content="hello",
        pics=[],
        publish_time="2026-09-26T18:00:00",
        source_url="https://www.bilibili.com/opus/new-1",
    )

    class Response:
        status_code = 200

        def json(self):
            return {"code": 0, "data": {"items": [{"id_str": "new-1"}], "offset": ""}}

    monkeypatch.setattr(fetcher.session, "get", lambda *args, **kwargs: Response())
    monkeypatch.setattr(fetcher, "_parse_bili_item", lambda *args, **kwargs: item)
    monkeypatch.setattr("src.world.bili_event_updater.official_feed_fetcher.time.sleep", lambda _: None)

    assert fetcher.fetch_all_new() == [item]
    assert fetcher.seen_ids == {}
    assert not cache_file.exists()
    fetcher.mark_processed([item])

    assert json.loads(cache_file.read_text(encoding="utf-8"))["36081646"] == ["new-1"]
    assert fetcher.fetch_all_new() == []


@pytest.mark.asyncio
async def test_bili_event_update_run_once_skips_without_updater():
    task = BiliEventUpdateTask({})

    result = await task.run_once()

    assert result.ok is True
    assert result.skipped is True


@pytest.mark.asyncio
async def test_bili_event_update_run_once_returns_counters():
    class FakeUpdater:
        async def fetch_and_update_events(self):
            return {"raw": 3, "parsed": 2, "updated": 1}

    task = BiliEventUpdateTask({})
    task.updater = FakeUpdater()

    result = await task.run_once()

    assert result.ok is True
    assert result.data == {"raw": 3, "parsed": 2, "updated": 1}


class _Fetcher:
    def __init__(self, cookie_ok=True, items=()):
        self.cookie_ok = cookie_ok
        self.items = list(items)
        self.processed = []

    async def check_and_update_cookie_validity(self):
        return self.cookie_ok

    def fetch_all_new(self):
        return list(self.items)

    def mark_processed(self, items):
        self.processed.extend(items)


class _Parser:
    def __init__(self, events=(), error=None):
        self.events = list(events)
        self.error = error

    async def parse_dynamics(self, raw_items):
        if self.error is not None:
            raise self.error
        return list(self.events)


class _EventStore:
    def __init__(self, results=None):
        self.results = list(results) if results is not None else None
        self.added = []

    async def add_event(self, event):
        self.added.append(event)
        return "id" if self.results is None else self.results.pop(0)


def _updater(fetcher=None, parser=None, event_store=None):
    updater = BiliEventUpdater()
    updater.fetcher = fetcher if fetcher is not None else _Fetcher()
    updater.parser = parser if parser is not None else _Parser()
    updater.event_store = event_store if event_store is not None else _EventStore()
    return updater


@pytest.mark.asyncio
async def test_bili_updater_requires_event_store():
    updater = BiliEventUpdater()
    with pytest.raises(RuntimeError):
        await updater.fetch_and_update_events()


@pytest.mark.asyncio
async def test_bili_updater_rejects_invalid_cookie():
    updater = _updater(fetcher=_Fetcher(cookie_ok=False))
    with pytest.raises(RuntimeError):
        await updater.fetch_and_update_events()


@pytest.mark.asyncio
async def test_bili_updater_returns_zero_counts_without_new_dynamics():
    updater = _updater(fetcher=_Fetcher(items=[]))
    assert await updater.fetch_and_update_events() == {"raw": 0, "parsed": 0, "updated": 0}


@pytest.mark.asyncio
async def test_bili_fetch_runs_off_event_loop():
    class ThreadRecordingFetcher(_Fetcher):
        def fetch_all_new(self):
            self.worker_thread_id = threading.get_ident()
            return []

    fetcher = ThreadRecordingFetcher()
    updater = _updater(fetcher=fetcher)

    await updater.fetch_and_update_events()

    assert fetcher.worker_thread_id != threading.get_ident()


@pytest.mark.asyncio
async def test_bili_updater_normalizes_events_and_counts_created_only():
    store = _EventStore(results=["e1", None])
    updater = _updater(
        fetcher=_Fetcher(items=[{"id": 1}]),
        parser=_Parser(events=[{"event_type": "concert"}, {"event_type": "release"}]),
        event_store=store,
    )
    counts = await updater.fetch_and_update_events()
    assert counts == {"raw": 1, "parsed": 2, "updated": 1}
    first, second = store.added
    assert first["event_type"] == UnifiedEventType.CONCERT.value
    assert first["source"] == "bilibili"
    assert first["is_recurring"] is False
    assert first["is_personal"] is False
    assert second["event_type"] == UnifiedEventType.GENERAL.value
    assert updater.fetcher.processed == [{"id": 1}]


@pytest.mark.asyncio
async def test_bili_updater_reports_parse_failure_and_does_not_acknowledge():
    updater = _updater(
        fetcher=_Fetcher(items=[{"id": 1}]),
        parser=_Parser(error=RuntimeError("parse boom")),
    )
    with pytest.raises(RuntimeError, match="parse boom"):
        await updater.fetch_and_update_events()
    assert updater.fetcher.processed == []


@pytest.mark.asyncio
async def test_bili_updater_reports_store_failure_and_does_not_acknowledge():
    class BrokenStore:
        async def add_event(self, event):
            raise RuntimeError("store boom")

    updater = _updater(
        fetcher=_Fetcher(items=[{"id": 1}]),
        parser=_Parser(events=[{"event_type": "concert"}]),
        event_store=BrokenStore(),
    )
    with pytest.raises(RuntimeError, match="store boom"):
        await updater.fetch_and_update_events()
    assert updater.fetcher.processed == []


def test_bili_event_type_mapping_is_normalized():
    assert BiliEventUpdater._map_old_event_type("concert") == UnifiedEventType.CONCERT.value
    assert BiliEventUpdater._map_old_event_type("livestream") == UnifiedEventType.LIVESTREAM.value
    assert BiliEventUpdater._map_old_event_type("release") == UnifiedEventType.GENERAL.value
    assert BiliEventUpdater._map_old_event_type("unknown") == UnifiedEventType.GENERAL.value


@pytest.mark.asyncio
async def test_bili_event_update_task_reports_failure_without_raising():
    class FakeUpdater:
        async def fetch_and_update_events(self):
            raise RuntimeError("Bilibili cookie is invalid or missing")

    task = BiliEventUpdateTask({})
    task.updater = FakeUpdater()

    result = await task.run_once()

    assert result.ok is False
    assert "cookie" in result.message.lower()


def test_bili_event_update_requires_dependencies_and_stays_mechanical():
    task = BiliEventUpdateTask({}, character_id="miku")
    with pytest.raises(RuntimeError):
        task.ensure_dependencies()
    assert task.task_name == "bili_event_update:miku"
    assert not hasattr(task, "agent_runtime")
