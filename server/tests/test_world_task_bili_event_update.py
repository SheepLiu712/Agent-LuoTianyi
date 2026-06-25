import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

import src.world.bili_event_updater.task as task_module
from src.world.bili_event_updater.task import BiliEventUpdateTask


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
