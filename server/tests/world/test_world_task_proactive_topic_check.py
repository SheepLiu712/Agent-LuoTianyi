from types import SimpleNamespace

import pytest

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
async def test_proactive_topic_check_only_wakes_stage_scan():
    calls = []

    class StageManager:
        async def scan_due_events(self):
            calls.append("run")

    runtime = SimpleNamespace(stage_manager=StageManager())
    task = ProactiveTopicCheckTask()
    task.initialize(runtime)

    result = await task.run_once()

    assert result.ok is True
    assert calls == ["run"]
