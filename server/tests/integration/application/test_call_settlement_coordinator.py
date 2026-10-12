import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from src.application.call import CallSettlementCoordinator
from src.application.user.reset_fence import UserResetFence
from src.domain.call import CallEndReason, CallFinalSnapshot, CallOutcome, CallTerminalFacts


def _snapshot(call_id):
    return CallFinalSnapshot(
        CallTerminalFacts(call_id, CallOutcome.CONNECTED, CallEndReason.USER_HANGUP, 1, datetime.now(timezone.utc)),
        (),
        0,
    )


class _Resources:
    def __init__(self):
        self.released = []
        self.maintenance_released = []

    def release_call_resources(self, call_id):
        self.released.append(call_id)
        return True

    def release_call_maintenance(self, call_id):
        self.maintenance_released.append(call_id)


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

    coordinator = CallSettlementCoordinator(consumer=Consumer(), resources=resources, timeout_seconds=0.01)
    await coordinator.emit(_snapshot(call_id))
    await coordinator.emit(_snapshot(call_id))
    await coordinator.close()

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

    coordinator = CallSettlementCoordinator(consumer=Consumer(), resources=resources, timeout_seconds=0.01)
    await coordinator.emit(_snapshot(call_id))
    await started.wait()
    await asyncio.sleep(0.02)
    assert resources.released == []

    cleanup_gate.set()
    await coordinator.close()

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

    coordinator = CallSettlementCoordinator(consumer=Consumer(), resources=resources, timeout_seconds=0.01)
    await coordinator.emit(_snapshot(call_id))
    await asyncio.to_thread(thread_started.wait)
    await asyncio.sleep(0.02)
    assert resources.released == []
    assert writes == []

    thread_gate.set()
    await coordinator.close()

    assert writes == ["created"]
    assert resources.released == [call_id]


@pytest.mark.asyncio
async def test_user_reset_fence_blocks_settlement_admission_and_waits_owned_write():
    owner_call = uuid4()
    other_call = uuid4()
    fence = UserResetFence()
    resources = _Resources()
    gate = asyncio.Event()

    class Consumer:
        async def settle(self, snapshot):
            await gate.wait()

    owners = {
        owner_call: type("Record", (), {"user_id": "owner"})(),
        other_call: type("Record", (), {"user_id": "other"})(),
    }
    coordinator = CallSettlementCoordinator(
        consumer=Consumer(),
        resources=resources,
        user_reset_fence=fence,
        call_owner=owners.get,
    )
    await coordinator.emit(_snapshot(owner_call))
    original_task = coordinator._tasks[owner_call]
    token = await fence.begin("owner")
    with pytest.raises(RuntimeError, match="RESET_IN_PROGRESS"):
        await coordinator.emit(_snapshot(owner_call))
    assert resources.maintenance_released == [owner_call]
    assert resources.released == [owner_call]
    assert coordinator._tasks[owner_call] is original_task
    await coordinator.emit(_snapshot(other_call))
    waiting = asyncio.create_task(coordinator.wait_user("owner"))
    await asyncio.sleep(0)
    assert not waiting.done()
    gate.set()
    await waiting
    await fence.end("owner", token)
    await coordinator.close()
