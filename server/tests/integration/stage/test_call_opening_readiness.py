"""装配就绪以实际开场发送为准，不给合法SQL尾部附加1秒产品SLA。"""

import asyncio
import threading

import pytest
from support import call_omni as helper

from src.domain.call import CallState
from src.domain.stage.lifecycle import StageEndReason


@pytest.fixture
def call_setup(tmp_path):
    return helper.call_setup.__wrapped__(tmp_path)


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", [False, True], ids=["late-success", "answer-failure"])
async def test_create_stage_waits_for_answer_pipeline_and_cleans_setup_failure(call_setup, monkeypatch, failed):
    repository, record, _, _ = call_setup
    entered, release = threading.Event(), threading.Event()
    real_update = repository.update_if_state
    real_stage = helper.CallStage
    real_socket = helper.FakeAliyunWebSocket
    seen = {}
    original_error = OSError("controlled answer state commit failed")

    def update(call_id, *, expected_state, record):
        result = real_update(call_id, expected_state=expected_state, record=record)
        if record.state is CallState.ACTIVE:
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test ACTIVE return gate not released")
            if failed:
                raise original_error
        return result

    def capture_stage(**kwargs):
        stage = real_stage(**kwargs)
        seen["stage"] = stage
        return stage

    def capture_socket():
        socket = real_socket()
        seen["socket"] = socket
        return socket

    monkeypatch.setattr(repository, "update_if_state", update)
    monkeypatch.setattr(helper, "CallStage", capture_stage)
    monkeypatch.setattr(helper, "FakeAliyunWebSocket", capture_socket)
    creating = asyncio.create_task(helper.create_stage(call_setup))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        stage, socket = seen["stage"], seen["socket"]
        assert stage.state is CallState.ACTIVE
        assert repository.find_by_id(record.call_id).state is CallState.ACTIVE
        assert not any(item["type"] == "response.create" for item in socket.sent)

        # 这是旧helper的已知错误等待边界，不是生产就绪SLA或用于修复的sleep。
        done, _ = await asyncio.wait({creating}, timeout=1.1)
        assert not done, "ACTIVE持久化返回仍在门内，装配应继续等接听动作而不是自己的1秒超时"
        release.set()
        if failed:
            with pytest.raises(OSError) as caught:
                await asyncio.wait_for(creating, 2)
            assert caught.value is original_error
            assert socket.closed and not stage.tasks
            assert not any(item["type"] == "response.create" for item in socket.sent)
        else:
            ready, returned_socket, _, _ = await asyncio.wait_for(creating, 2)
            assert ready is stage and returned_socket is socket
            assert stage.state is CallState.ACTIVE and not stage.termination_requested
            assert repository.find_by_id(record.call_id).state is CallState.ACTIVE
            assert sum(item["type"] == "response.create" for item in socket.sent) == 1
    finally:
        release.set()
        if not creating.done():
            creating.cancel()
        await asyncio.gather(creating, return_exceptions=True)
        if "stage" in seen:
            result = await asyncio.wait_for(seen["stage"].terminate(StageEndReason.USER_REQUESTED), 2)
            assert result.resources_released
            assert seen["socket"].closed and not seen["stage"].tasks
