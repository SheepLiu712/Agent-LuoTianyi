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
from src.agent.skills.knowledge.song_acceptance import SongAcceptanceStatus, SongKnowledgeAcceptanceSkill
from src.infrastructure.models.service import LLMService
from src.infrastructure.persistence import Song, get_song_session
from src.utils.helpers import load_config
from src.world.bili_event_updater.task import BiliEventUpdateTask
from src.world.get_new_songs.task import VCPediaNewSongTask

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


@pytest.mark.asyncio
async def test_vcpedia_run_once_fetches_live_songs_and_writes_result(monkeypatch, tmp_path):
    config = load_config("config/config.json")
    task_config = copy.deepcopy(config["world"]["song_knowledge"])
    knowledge_dir = tmp_path / "knowledge"
    task_config["song_database"] = {
        "db_folder": str(knowledge_dir),
        "db_file": "knowledge_db.db",
    }
    task_config.setdefault("crawler", {})
    task_config["crawler"]["output_dir"] = str(tmp_path / "crawled_data")
    task_config["crawler"]["data_dir"] = str(tmp_path / "uncached_data")
    task_config["crawler"]["use_llm"] = False

    # Fetch the real template, then bound this external probe to a few real pages.
    sampled_songs = fetcher_module.fetch_song_list_from_template(fetcher_module.TEMPLATE_URL)[:3]
    assert sampled_songs, "VCPedia template returned no song links"
    monkeypatch.setattr(fetcher_module, "fetch_song_list_from_template", lambda _url: sampled_songs)
    monkeypatch.setattr(fetcher_module.time, "sleep", lambda _seconds: None)

    submitted_facts: list[Any] = []

    class FactSink:
        async def submit(self, fact: Any) -> bool:
            submitted_facts.append(fact)
            return True

    async def get_world_stage(character_id: str):
        assert character_id == "luotianyi"
        return SimpleNamespace(fact_sink=FactSink())

    task = VCPediaNewSongTask(task_config)
    task.initialize(
        SimpleNamespace(
            llm_service=None,
            agent_runtime=SimpleNamespace(default_character_id="luotianyi"),
            get_world_stage=get_world_stage,
        )
    )

    result = await task.run_once()
    payload = {
        "ok": result.ok,
        "message": result.message,
        "discovered_count": result.data.get("discovered_count", 0),
        "submitted_count": result.data.get("submitted_count", 0),
        "rejected_count": result.data.get("rejected_count", 0),
        "skipped_existing_count": result.data.get("skipped_existing_count", 0),
        "fetch_failed_count": result.data.get("fetch_failed_count", 0),
        "discovered": result.data.get("discovered", []),
        "skipped_existing": result.data.get("skipped_existing", []),
        "fetch_failed": result.data.get("fetch_failed", []),
    }
    _write_result_file(payload)

    assert result.ok is True, result.message
    assert payload["discovered_count"] == len(payload["discovered"])
    assert payload["submitted_count"] == len(submitted_facts)
    assert payload["rejected_count"] == 0
    assert submitted_facts, f"No song pages produced an accepted candidate; see {VCPEDIA_OUTPUT_FILE}"

    # World dispatches a fact; the Agent-owned acceptance skill persists it.
    fact = submitted_facts[0]
    skill = SongKnowledgeAcceptanceSkill({**task_config, "knowledge_dir": str(knowledge_dir)})
    accepted = await skill.accept(
        source_ref=fact.source_ref,
        external_song_id=fact.external_song_id,
        revision=fact.revision,
        candidate=fact.candidate,
    )
    assert accepted.status is SongAcceptanceStatus.ACCEPTED
    session = get_song_session()
    try:
        assert session.query(Song).filter(Song.name == fact.candidate.song_name).one()
    finally:
        session.close()
    keywords = (knowledge_dir / "song_name_keywords.txt").read_text(encoding="utf-8").splitlines()
    assert fact.candidate.song_name in keywords


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
