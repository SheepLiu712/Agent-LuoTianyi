"""迁移准入使用真实 StageManager/Fence：聊天收尾成功才可取得变更令牌。"""

import asyncio
from types import SimpleNamespace

import pytest

from src.application.user.reset_fence import UserResetFence
from src.domain.stage.lifecycle import StageEndReason, StageLifecycleState, StageTerminationResult
from src.stage.chat.chat_stage import ChatStage
from src.stage.stage_manager import StageManager


class TransferChat(ChatStage):
    def __init__(self, *, error=None, released=True):
        self.suspended = False
        self.reason = None
        self.finished = False
        self.error = error
        self.released = released

    @property
    def lifecycle_state(self):
        return StageLifecycleState.RUNNING

    def set_input_suspended(self, suspended):
        self.suspended = suspended

    def begin_termination(self, reason):
        self.reason = reason

    async def terminate(self, reason):
        await asyncio.sleep(0)
        assert self.suspended
        self.finished = True
        return StageTerminationResult(
            interaction_id="test-chat",
            reason=reason,
            finalization_error=self.error,
            resources_released=self.released,
        )


def manager(stage):
    result = object.__new__(StageManager)
    result._lock = asyncio.Lock()
    result._closed = False
    result._user_reset_fence = UserResetFence()
    result._stages = {("owner", "luotianyi"): stage}
    result._managed = {"test-chat": SimpleNamespace(user_id="owner", stage=stage)}
    result._finalizations = SimpleNamespace(has_user=lambda _: False)
    result._chat_creations = {}
    result._call_ownerships = {}
    result._call_claims = {}
    result._call_start_operations = {}
    result._call_stage_creations = {}
    return result


def test_transfer_waits_for_chat_and_holds_owner_only_admission():
    async def scenario():
        stage = TransferChat()
        subject = manager(stage)
        token = await subject.begin_user_data_transfer("owner")
        assert stage.finished and stage.reason is StageEndReason.USER_REQUESTED
        with pytest.raises(RuntimeError, match="USER_DATA_RESET_IN_PROGRESS"):
            await subject._user_reset_fence.require_admission("owner")
        await subject._user_reset_fence.require_admission("other")
        await subject.end_user_data_reset("owner", token)
        await subject._user_reset_fence.require_admission("owner")

    asyncio.run(scenario())


@pytest.mark.parametrize("error,released", [("maintenance failed", True), (None, False)])
def test_failed_maintenance_or_cleanup_never_grants_transfer(error, released):
    async def scenario():
        subject = manager(TransferChat(error=error, released=released))
        with pytest.raises(RuntimeError, match="USER_DATA_TRANSFER_FINALIZATION_FAILED"):
            await subject.begin_user_data_transfer("owner")
        assert not subject._user_reset_fence.is_resetting("owner")

    asyncio.run(scenario())


@pytest.mark.parametrize("busy", ["call", "creation", "finalization", "handoff"])
def test_call_or_incomplete_lifecycle_is_rejected_before_suspending_chat(busy):
    async def scenario():
        stage = TransferChat()
        subject = manager(stage)
        if busy == "call":
            subject._managed["call"] = SimpleNamespace(user_id="owner", stage=object())
        elif busy == "creation":
            subject._chat_creations[("owner", "luotianyi")] = object()
        elif busy == "finalization":
            subject._finalizations = SimpleNamespace(has_user=lambda _: True)
        else:
            subject._call_start_operations["request"] = ("owner", "luotianyi", "test-chat")
        with pytest.raises(RuntimeError, match="USER_INTERACTION_BUSY"):
            await subject.begin_user_data_transfer("owner")
        assert not stage.suspended and not stage.finished
        assert not subject._user_reset_fence.is_resetting("owner")

    asyncio.run(scenario())
