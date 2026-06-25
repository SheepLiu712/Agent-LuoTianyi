import sys
import types
from pathlib import Path
from types import SimpleNamespace

server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.world.get_new_songs.task import VCPediaNewSongTask


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
    fake_module = types.ModuleType("src.world.get_new_songs.daily_new_song_fetcher")
    calls = {}

    def sync_daily_new_songs(config, llm_module=None):
        calls["config"] = config
        calls["llm_module"] = llm_module
        return {"added": ["A", "B"], "failed": ["C"]}

    fake_module.sync_daily_new_songs = sync_daily_new_songs
    monkeypatch.setitem(sys.modules, fake_module.__name__, fake_module)
    task = VCPediaNewSongTask({"crawler": {}})
    task.llm_module = "llm"

    result = task.run_once()

    assert result.ok is True
    assert result.data["added_count"] == 2
    assert result.data["failed_count"] == 1
    assert calls["llm_module"] == "llm"


def test_vcpedia_run_once_returns_failure_on_exception(monkeypatch):
    fake_module = types.ModuleType("src.world.get_new_songs.daily_new_song_fetcher")

    def sync_daily_new_songs(config, llm_module=None):
        raise RuntimeError("boom")

    fake_module.sync_daily_new_songs = sync_daily_new_songs
    monkeypatch.setitem(sys.modules, fake_module.__name__, fake_module)
    task = VCPediaNewSongTask({})

    result = task.run_once()

    assert result.ok is False
    assert "boom" in result.message
