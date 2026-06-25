import copy
import json
import os
import sys
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

import src.world.bili_event_updater.task as task_module
from src.world.bili_event_updater.task import BiliEventUpdateTask
from src.utils.helpers import load_config
from src.utils.llm_service import LLMService


OUTPUT_FILE = Path("data/test_outputs/bili_event_update_latest.json")


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


class FakeEventStore:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def add_event(self, event: dict[str, Any]) -> str:
        self.events.append(_jsonable(event))
        return f"fake-event-{len(self.events)}"


def _write_capture_file(payload: dict[str, Any]) -> None:
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(
        json.dumps(_jsonable(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


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
    assert captured["vlm_module"][0] == "vlm"
    assert task.get_task_type() == "interval"


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


@pytest.mark.asyncio
async def test_bili_event_update_fetches_live_dynamics_and_captures_events(tmp_path):
    cookie_file = Path("config/bili_cookie.txt")
    if not cookie_file.exists() or not cookie_file.read_text(encoding="utf-8-sig").strip():
        pytest.skip("config/bili_cookie.txt is required for live Bilibili dynamic fetching")
    if not os.environ.get("QWEN_API_KEY"):
        pytest.skip("QWEN_API_KEY is required for live Bilibili event parsing")

    config = load_config("config/config.json")
    world_config = copy.deepcopy(config["world"]["bili_dynamic_fetcher"])
    world_config["data_file"] = str(tmp_path / "feed_cache.json")

    event_store = FakeEventStore()
    llm_service = LLMService(config["llm_service"])
    runtime = SimpleNamespace(
        database_manager=SimpleNamespace(event_store=event_store),
        llm_service=llm_service,
    )
    task = BiliEventUpdateTask(world_config)
    task.initialize(runtime)

    assert task.updater is not None
    captured_raw: list[dict[str, Any]] = []
    original_fetch_all_new = task.updater.fetcher.fetch_all_new

    def capture_fetch_all_new():
        raw_items = original_fetch_all_new()
        captured_raw.extend(_jsonable(item) for item in raw_items)
        return raw_items

    task.updater.fetcher.fetch_all_new = capture_fetch_all_new

    result = await task.run_once()
    capture = {
        "result": _jsonable(result),
        "raw_dynamics": captured_raw,
        "events": event_store.events,
    }
    _write_capture_file(capture)

    assert result.ok is True, result.message
    assert result.data["raw"] == len(captured_raw)
    assert result.data["parsed"] == len(event_store.events)
    assert result.data["updated"] == len(event_store.events)
    assert captured_raw, f"No Bilibili dynamics were captured; see {OUTPUT_FILE}"
    assert event_store.events, f"No events were parsed from fetched dynamics; see {OUTPUT_FILE}"
