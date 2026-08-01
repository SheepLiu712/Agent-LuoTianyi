import sys
from pathlib import Path

import pytest


server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.chat_session.call_settlement import CallSettlementCoordinator


class FlakyMind:
    def __init__(self):
        self.calls = []

    async def write_topic_memories(self, **kwargs):
        self.calls.append(kwargs["current_dialogue"])
        if len(self.calls) == 1:
            raise RuntimeError("temporary write failure")


@pytest.mark.asyncio
async def test_failed_memory_batch_is_retried_before_cursor_advances():
    mind = FlakyMind()
    runtime = type("Runtime", (), {"mind": mind})()
    agent_runtime = type(
        "AgentRuntime",
        (),
        {"get_character_runtime": lambda self, _character: runtime},
    )()
    coordinator = CallSettlementCoordinator(
        config={},
        llm_service=None,
        call_store=object(),
        agent_runtime=agent_runtime,
        character_id="luotianyi",
    )
    turns = [
        {"speaker": "user", "text": f"line-{index}"}
        for index in range(10)
    ]

    await coordinator.write_memory_incremental(
        call_id="call-1",
        user_id="user-1",
        turns=turns,
    )
    assert coordinator._memory_batch_index == 0
    assert coordinator.memory_error == "temporary write failure"

    await coordinator.write_memory_incremental(
        call_id="call-1",
        user_id="user-1",
        turns=turns,
        final=True,
    )

    assert coordinator._memory_batch_index == 10
    assert coordinator.memory_error is None
    assert mind.calls[0] == mind.calls[1]
