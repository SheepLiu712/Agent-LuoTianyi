import copy
import json
import os
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import src.world.get_new_songs.daily_new_song_fetcher as fetcher_module
from src.utils.helpers import load_config
from src.utils.llm_service import LLMService
from src.world.get_new_songs.task import VCPediaNewSongTask
from src.world.bili_event_updater.task import BiliEventUpdateTask

VCPEDIA_OUTPUT_FILE = Path("data/test_outputs/vcpedia_new_songs_latest.json")
BILI_OUTPUT_FILE = Path("data/test_outputs/bili_event_update_latest.json")


def _write_result_file(payload):
    VCPEDIA_OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    VCPEDIA_OUTPUT_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


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
    BILI_OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    BILI_OUTPUT_FILE.write_text(
        json.dumps(_jsonable(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_vcpedia_run_once_fetches_live_songs_and_writes_result(monkeypatch, tmp_path):
    config = load_config("config/config.json")
    task_config = copy.deepcopy(config["world"]["song_knowledge"])
    task_config["song_database"] = {
        "db_folder": str(tmp_path / "knowledge"),
        "db_file": "knowledge_db.db",
    }
    task_config.setdefault("crawler", {})
    task_config["crawler"]["output_dir"] = str(tmp_path / "crawled_data")
    task_config["crawler"]["use_llm"] = False

    keyword_dir = tmp_path / "keywords"
    monkeypatch.setattr(fetcher_module, "KNOWLEDGE_DIR", keyword_dir)
    monkeypatch.setattr(fetcher_module, "SONG_NAME_KEYWORDS_FILE", keyword_dir / "song_name_keywords.txt")
    monkeypatch.setattr(fetcher_module, "SONG_LYRIC_KEYWORDS_FILE", keyword_dir / "song_lyric_keywords.txt")
    monkeypatch.setattr(fetcher_module.time, "sleep", lambda _seconds: None)

    task = VCPediaNewSongTask(task_config)
    task.initialize(SimpleNamespace(llm_service=None))

    result = task.run_once()
    payload = {
        "ok": result.ok,
        "message": result.message,
        "added_count": result.data.get("added_count", 0),
        "failed_count": result.data.get("failed_count", 0),
        "added": result.data.get("added", []),
        "failed": result.data.get("failed", []),
    }
    _write_result_file(payload)

    assert result.ok is True, result.message
    assert payload["added_count"] == len(payload["added"])
    assert payload["failed_count"] == len(payload["failed"])
    assert payload["added"] or payload["failed"], f"No songs were fetched; see {VCPEDIA_OUTPUT_FILE}"


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
    assert captured_raw, f"No Bilibili dynamics were captured; see {BILI_OUTPUT_FILE}"
    assert event_store.events, f"No events were parsed from fetched dynamics; see {BILI_OUTPUT_FILE}"
