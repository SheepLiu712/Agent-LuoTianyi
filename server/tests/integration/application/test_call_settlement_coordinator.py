import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from src.application.call import CallSettlementCoordinator
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

    def release_call_resources(self, call_id):
        self.released.append(call_id)
        return True


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
