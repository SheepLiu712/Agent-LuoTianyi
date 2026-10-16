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


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["success", "failure", "timeout"])
async def test_settlement_completes_without_shared_agent_resource_release(mode):
    call_id = uuid4()

    class Consumer:
        async def settle(self, snapshot, *, context=None, deadline=None):
            assert snapshot.terminal.call_id == call_id
            if mode == "failure":
                raise RuntimeError("failed")
            if mode == "timeout":
                await asyncio.Event().wait()

    settlement = CallSettlement(consumer=Consumer(), timeout_seconds=0.01)
    await settlement.settle(_snapshot(call_id))


@pytest.mark.asyncio
async def test_timeout_waits_for_owned_consumer_cleanup():
    call_id = uuid4()
    started = asyncio.Event()
    cleanup_gate = asyncio.Event()

    class Consumer:
        async def settle(self, snapshot, *, context=None, deadline=None):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await cleanup_gate.wait()
                raise

    settlement = CallSettlement(consumer=Consumer(), timeout_seconds=0.01)
    task = asyncio.create_task(settlement.settle(_snapshot(call_id)))
    await started.wait()
    await asyncio.sleep(0.02)
    cleanup_gate.set()
    await task


@pytest.mark.asyncio
async def test_timeout_during_owned_batch_create_waits_until_repository_returns():
    call_id = uuid4()
    thread_started = __import__("threading").Event()
    thread_gate = __import__("threading").Event()
    writes = []

    class Consumer:
        async def settle(self, snapshot, *, context=None, deadline=None):
            from src.utils.owned_operation import complete_owned

            def create_batch():
                thread_started.set()
                thread_gate.wait()
                writes.append("created")

            await complete_owned(asyncio.to_thread(create_batch))
            raise asyncio.CancelledError

    settlement = CallSettlement(consumer=Consumer(), timeout_seconds=0.01)
    task = asyncio.create_task(settlement.settle(_snapshot(call_id)))
    await asyncio.to_thread(thread_started.wait)
    await asyncio.sleep(0.02)
    assert writes == []

    thread_gate.set()
    await task

    assert writes == ["created"]
