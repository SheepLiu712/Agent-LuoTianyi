import json
import sys
from datetime import datetime
from pathlib import Path

server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.system.database.event_store import EventStore
from src.system.database.sql_database import Event, get_sql_session, init_sql_db


class NoopRedis:
    pass


class FakeLLMModule:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def generate_response(self, **kwargs):
        self.calls.append(kwargs)
        return json.dumps(self.payload, ensure_ascii=False)


def test_event_store_prompt_files_exist():
    prompt_dir = Path(server_root) / "res" / "agent" / "prompts"
    event_prompt = json.loads((prompt_dir / "event_store_prompt.json").read_text(encoding="utf-8"))
    memory_prompt = json.loads((prompt_dir / "memory_store_prompt.json").read_text(encoding="utf-8"))

    assert event_prompt["name"] == "event_store_prompt"
    assert memory_prompt["name"] == "memory_store_prompt"


def test_find_matching_event_with_llm_uses_prompt_module(tmp_path):
    init_sql_db(str(tmp_path), "events.db")
    db = get_sql_session()
    try:
        db.add(
            Event(
                id="existing-event",
                event_type="concert",
                title="Concert A",
                description="old description",
                start_datetime=datetime(2026, 7, 1, 20, 0, 0),
                is_active=True,
                is_recurring=False,
                source="bilibili",
            )
        )
        db.commit()
    finally:
        db.close()

    llm = FakeLLMModule(
        {
            "match": True,
            "matched_id": "existing-event",
            "merged_description": "merged description",
        }
    )
    store = EventStore({}, get_sql_session, NoopRedis(), llm_module=llm)

    import asyncio

    result = asyncio.run(
        store._find_matching_event_with_llm(
            title="Concert A additional notice",
            description="new description",
            event_type="concert",
            start_datetime=datetime(2026, 7, 2, 19, 0, 0),
            date_mmdd=None,
        )
    )

    assert result is not None
    assert result["id"] == "existing-event"
    assert result["_merged_description"] == "merged description"
    assert llm.calls
    assert llm.calls[0]["title"] == "Concert A additional notice"
    assert "existing-event" in llm.calls[0]["candidates"]


def test_find_matching_event_with_llm_returns_none_without_module():
    store = EventStore({}, lambda: None, NoopRedis(), llm_module=None)

    import asyncio

    result = asyncio.run(
        store._find_matching_event_with_llm(
            title="A",
            description="B",
            event_type="general",
            start_datetime=None,
            date_mmdd=None,
        )
    )

    assert result is None
