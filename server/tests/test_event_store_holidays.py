import sys
from pathlib import Path


server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

import src.system.database.event_store as event_store_module
from src.system.database.event_store import EventStore


class NoopRedis:
    pass


async def test_existing_fixed_holiday_does_not_skip_later_missing_holiday(monkeypatch):
    store = EventStore({}, lambda: None, NoopRedis())
    created = []

    async def find_matching_event(title, **kwargs):
        return {"id": "existing"} if title == "Existing Holiday" else None

    async def add_event(event_data):
        created.append(event_data)
        return "created"

    monkeypatch.setattr(
        event_store_module,
        "FIXED_SOLAR_HOLIDAYS",
        {
            "01-01": ("Existing Holiday", "already stored"),
            "02-02": ("Missing Holiday", "must be added"),
        },
    )
    monkeypatch.setattr(event_store_module, "LUNAR_HOLIDAYS_MMDD", {})
    monkeypatch.setattr(event_store_module, "is_lunar_new_year_eve", lambda *args: False)
    monkeypatch.setattr(store, "find_matching_event", find_matching_event)
    monkeypatch.setattr(store, "add_event", add_event)

    added = await store.ensure_holidays([2026])

    assert added == 1
    assert [event["title"] for event in created] == ["Missing Holiday"]
