import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

import src.world.get_new_songs.task as task_module
import src.world.get_new_songs.daily_new_song_fetcher as fetcher_module
from src.utils.helpers import load_config
from src.world.get_new_songs.task import VCPediaNewSongTask


OUTPUT_FILE = Path("data/test_outputs/vcpedia_new_songs_latest.json")


def _write_result_file(payload):
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_vcpedia_initialize_registers_llm_when_enabled():
    class FakeLLMService:
        def __init__(self):
            self.calls = []

        def register_llm_module(self, name, config):
            self.calls.append((name, config))
            return "llm-module"

    cfg = {"crawler": {"use_llm": True, "llm_module": {"prompt_name": "p"}}}
    service = FakeLLMService()
    task = VCPediaNewSongTask(cfg)

    task.initialize(SimpleNamespace(llm_service=service))

    assert task.llm_module == "llm-module"
    assert service.calls == [("song_knowledge_crawler", {"prompt_name": "p"})]


def test_vcpedia_initialize_skips_when_llm_disabled():
    task = VCPediaNewSongTask({"crawler": {"use_llm": False}})

    task.initialize(SimpleNamespace(llm_service=object()))

    assert task.llm_module is None


def test_vcpedia_run_once_reports_counts(monkeypatch):
    calls = {}

    def sync_daily_new_songs(config, llm_module=None):
        calls["config"] = config
        calls["llm_module"] = llm_module
        return {"added": ["A", "B"], "failed": ["C"]}

    monkeypatch.setattr(task_module, "sync_daily_new_songs", sync_daily_new_songs)
    task = VCPediaNewSongTask({"crawler": {}})
    task.llm_module = "llm"

    result = task.run_once()

    assert result.ok is True
    assert result.data["added_count"] == 2
    assert result.data["failed_count"] == 1
    assert calls["llm_module"] == "llm"


def test_vcpedia_run_once_returns_failure_on_exception(monkeypatch):
    def sync_daily_new_songs(config, llm_module=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(task_module, "sync_daily_new_songs", sync_daily_new_songs)
    task = VCPediaNewSongTask({})

    result = task.run_once()

    assert result.ok is False
    assert "boom" in result.message


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
    assert payload["added"] or payload["failed"], f"No songs were fetched; see {OUTPUT_FILE}"
