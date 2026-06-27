import os
import sys
from pathlib import Path
from types import SimpleNamespace

server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.world.citywalk.task import CitywalkTask


class FakeEventStore:
    def __init__(self):
        self.events = []

    async def add_event(self, event):
        self.events.append(event)
        return "event-id"


def test_citywalk_normalize_overview():
    assert CitywalkTask._normalize_overview("report.md").endswith("report.md")
    assert CitywalkTask._normalize_overview("plain summary") == "plain summary"


def test_citywalk_run_once_skips_without_service():
    task = CitywalkTask({})

    result = task.run_once()

    assert result.ok is True
    assert result.skipped is True


def test_citywalk_run_once_writes_travel_event():
    event_store = FakeEventStore()
    task = CitywalkTask({})
    task.event_store = event_store
    task.citywalk_service = SimpleNamespace(run_once=lambda: "data/citywalk_reports/today.md")

    result = task.run_once()

    assert result.ok is True
    assert result.data["output_path"].endswith("today.md")
    assert len(event_store.events) == 1
    event = event_store.events[0]
    assert event["event_type"] == "travel"
    assert event["source"] == "world_citywalk"
    assert "today.md" in event["description"]


def test_citywalk_run_once_skips_when_no_diary():
    task = CitywalkTask({})
    task.citywalk_service = SimpleNamespace(run_once=lambda: "")

    result = task.run_once()

    assert result.ok is True
    assert result.skipped is True


def test_citywalk_build_llm_modules_registers_expected_modules():
    class FakeLLMService:
        def __init__(self):
            self.llm_names = []
            self.vlm_names = []

        def register_llm_module(self, name, config):
            self.llm_names.append((name, config))
            return SimpleNamespace(name=name)

        def register_vlm_module(self, name, config):
            self.vlm_names.append((name, config))
            return SimpleNamespace(name=name)

    llm_service = FakeLLMService()
    task = CitywalkTask({"decision": {"llm": {"name": "test-model"}}})
    task.system_runtime = SimpleNamespace(llm_service=llm_service)

    modules = task._build_llm_modules()

    assert modules.json_module.name == "citywalk_json"
    assert modules.text_module.name == "citywalk_text"
    assert modules.vlm_module.name == "citywalk_vlm"
    assert [name for name, _ in llm_service.llm_names] == ["citywalk_json", "citywalk_text"]
    assert [name for name, _ in llm_service.vlm_names] == ["citywalk_vlm"]


def test_citywalk_build_citywalk_service_skips_without_runtime():
    task = CitywalkTask({})

    assert task._build_citywalk_service() is None


def test_citywalk_build_citywalk_service_skips_without_vector_store():
    task = CitywalkTask({})
    task.system_runtime = SimpleNamespace(agent_runtime=SimpleNamespace(vector_store=None))

    assert task._build_citywalk_service() is None


def test_citywalk_initialize_uses_runtime_dependencies(monkeypatch):
    task = CitywalkTask({})
    built = object()
    monkeypatch.setattr(task, "_build_citywalk_service", lambda: built)
    event_store = object()
    runtime = SimpleNamespace(database_manager=SimpleNamespace(event_store=event_store))

    task.initialize(runtime)

    assert task.system_runtime is runtime
    assert task.event_store is event_store
    assert task.citywalk_service is built
