import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.world.proactive_topic_task import ProactiveTopicCheckTask


@pytest.mark.asyncio
async def test_proactive_topic_check_skips_without_runtime():
    task = ProactiveTopicCheckTask()

    result = await task.run_once()

    assert result.ok is True
    assert result.skipped is True


def test_proactive_topic_check_initialize_sets_runtime():
    task = ProactiveTopicCheckTask()
    runtime = object()

    task.initialize(runtime)

    assert task.system_runtime is runtime


@pytest.mark.asyncio
async def test_proactive_topic_check_runs_periodic_checks():
    calls = []

    class FakeMaker:
        async def run_periodic_checks(self, runtime):
            calls.append(runtime)

    runtime = SimpleNamespace(
        chat_session_manager=SimpleNamespace(proactive_topic_maker=FakeMaker())
    )
    task = ProactiveTopicCheckTask()
    task.initialize(runtime)

    result = await task.run_once()

    assert result.ok is True
    assert calls == [runtime]
