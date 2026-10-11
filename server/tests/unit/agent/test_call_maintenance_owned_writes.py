import asyncio
import threading

import pytest

import src.domain.agent as d
from src.agent.skills.adapters.memory.writer import MemoryWriter


@pytest.mark.asyncio
async def test_cancelled_maintenance_waits_for_started_write_and_does_not_start_next_projection():
    started = threading.Event()
    release = threading.Event()

    class Store:
        def __init__(self):
            self.records = []

        def write_agent_memory_record_if_absent(self, record):
            self.records.append(record.content)
            started.set()
            release.wait()

        def link_agent_memory_embeddings(self, *args, **kwargs):
            raise AssertionError("cancelled operation must not start embedding link")

    class Vector:
        def upsert_documents(self, *args, **kwargs):
            raise AssertionError("cancelled operation must not start vector write")

    writer = object.__new__(MemoryWriter)
    store = Store()
    task = asyncio.create_task(
        writer.write_maintenance_candidates(
            vector_store=Vector(),
            memory_store=store,
            user_id="user",
            owner_character_id="luotianyi",
            maintenance_id="maintenance",
            candidates=(
                d.MaintenanceCandidate(d.MaintenanceMemoryType.USER_FACT, "first"),
                d.MaintenanceCandidate(d.MaintenanceMemoryType.USER_FACT, "second"),
            ),
        )
    )
    await asyncio.to_thread(started.wait)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()

    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert store.records == ["first"]
