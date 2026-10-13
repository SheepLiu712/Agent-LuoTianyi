import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from src.domain.call import (
    CallEndReason,
    CallFinalSnapshot,
    CallOutcome,
    CallTerminalFacts,
)
from src.stage.call_settlement import CallSettlement


def _snapshot(call_id):
    return CallFinalSnapshot(
        CallTerminalFacts(call_id, CallOutcome.CONNECTED, CallEndReason.USER_HANGUP, 1, datetime.now(timezone.utc)),
        (),
        0,
    )


class _Resources:
    def __init__(self):
        self.released = []

    def release_call_maintenance(self, call_id):
        self.released.append(call_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["success", "failure", "timeout"])
async def test_settlement_always_releases_agent_resources(mode):
    call_id = uuid4()
    resources = _Resources()

    class Consumer:
        async def settle(self, snapshot):
            assert snapshot.terminal.call_id == call_id
            if mode == "failure":
                raise RuntimeError("failed")
            if mode == "timeout":
                await asyncio.Event().wait()

    settlement = CallSettlement(consumer=Consumer(), resources=resources, timeout_seconds=0.01)
    await settlement.settle(_snapshot(call_id))

    assert resources.released == [call_id]


@pytest.mark.asyncio
async def test_timeout_waits_for_owned_consumer_cleanup_before_releasing_resources():
    call_id = uuid4()
    resources = _Resources()
    started = asyncio.Event()
    cleanup_gate = asyncio.Event()

    class Consumer:
        async def settle(self, snapshot):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await cleanup_gate.wait()
                raise

    settlement = CallSettlement(consumer=Consumer(), resources=resources, timeout_seconds=0.01)
    task = asyncio.create_task(settlement.settle(_snapshot(call_id)))
    await started.wait()
    await asyncio.sleep(0.02)
    assert resources.released == []

    cleanup_gate.set()
    await task

    assert resources.released == [call_id]


@pytest.mark.asyncio
async def test_timeout_during_owned_batch_create_holds_resources_until_repository_returns():
    call_id = uuid4()
    resources = _Resources()
    thread_started = __import__("threading").Event()
    thread_gate = __import__("threading").Event()
    writes = []

    class Consumer:
        async def settle(self, snapshot):
            from src.utils.owned_operation import complete_owned

            def create_batch():
                thread_started.set()
                thread_gate.wait()
                writes.append("created")

            await complete_owned(asyncio.to_thread(create_batch))
            raise asyncio.CancelledError

    settlement = CallSettlement(consumer=Consumer(), resources=resources, timeout_seconds=0.01)
    task = asyncio.create_task(settlement.settle(_snapshot(call_id)))
    await asyncio.to_thread(thread_started.wait)
    await asyncio.sleep(0.02)
    assert resources.released == []
    assert writes == []

    thread_gate.set()
    await task

    assert writes == ["created"]
    assert resources.released == [call_id]
