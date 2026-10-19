"""验证跨交互并发、创建占用以及 Manager 持有的离线回收。"""

import asyncio

import pytest
from support.call_output import output_sink
from support.call_session_repository import InMemoryCallSessionRepository
from support.chat_connection import StubChatConnection
from support.realtime_speech import FakeRealtimeSpeechSessionFactory
from support.stage_manager import make_stage_manager

import src.domain.agent as d
from src.adapter.websocket.chat import WebSocketAdapter
from src.agent.context import ContextFactory
from src.application.user.reset_fence import UserResetFence
from src.domain.call import CallAnswerDecision, CallEndReason, CallState

from .test_call_stage import _Clock, _ContextDatabase, _Transport, _TurnHandler, _agent, _eventually
from .test_chat_stage import RecordingAgent, Socket, StageContextFactory


class _SlowChatFactory(StageContextFactory):
    def __init__(self):
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0
        self.fail = False

    async def create(self, *args, **kwargs):
        self.calls += 1
        if kwargs["user_id"] == "slow":
            self.entered.set()
            await self.release.wait()
            if self.fail:
                raise RuntimeError("context unavailable")
        return await super().create(*args, **kwargs)


def _chat_manager(factory, **config):
    adapter = WebSocketAdapter()
    manager = make_stage_manager(
        adapter=adapter,
        get_agent=lambda _: RecordingAgent(),
        get_context_factory=lambda _: factory,
        user_reset_fence=UserResetFence(),
        config=config,
    )
    return manager, adapter


@pytest.mark.asyncio
async def test_slow_chat_initialization_does_not_hold_global_manager_or_adapter_lock():
    factory = _SlowChatFactory()
    manager, adapter = _chat_manager(factory)
    first = asyncio.create_task(adapter.open(user_id="slow", connection_id=object()))
    try:
        await asyncio.wait_for(factory.entered.wait(), 1)
        other = await asyncio.wait_for(adapter.open(user_id="other", connection_id=object()), 1)
        assert other is not None and not first.done()
        with pytest.raises(RuntimeError, match="USER_INTERACTION_BUSY"):
            await asyncio.wait_for(manager.begin_user_data_reset("slow"), 1)
        token = await asyncio.wait_for(manager.begin_user_data_reset("idle"), 1)
        await manager.end_user_data_reset("idle", token)
        factory.release.set()
        await asyncio.wait_for(first, 1)
    finally:
        factory.release.set()
        await asyncio.gather(first, return_exceptions=True)
        await adapter.close()
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_same_identity_shares_creation_and_failed_creation_can_retry(fail):
    factory = _SlowChatFactory()
    factory.fail = fail
    manager, adapter = _chat_manager(factory)

    async def acquire():
        return await manager.try_to_get_stage(
            user_id="slow", character_id="luotianyi", connection=StubChatConnection(Socket(), "slow", "device")
        )

    first = asyncio.create_task(acquire())
    second = asyncio.create_task(acquire())
    try:
        await asyncio.wait_for(factory.entered.wait(), 1)
        await asyncio.sleep(0)
        assert factory.calls == 1
        factory.release.set()
        results = await asyncio.wait_for(asyncio.gather(first, second, return_exceptions=True), 1)
        if fail:
            assert all(isinstance(result, RuntimeError) for result in results)
            assert not manager._chat_creations and not manager._stages
            token = await manager.begin_user_data_reset("slow")
            await manager.end_user_data_reset("slow", token)
            factory.fail = False
            assert await acquire() is not None
            assert factory.calls == 2
        else:
            assert results[0] is results[1]
            assert len(factory.created) == 1
    finally:
        factory.release.set()
        await asyncio.gather(first, second, return_exceptions=True)
        await adapter.close()
        await manager.close()


@pytest.mark.asyncio
async def test_cancelled_open_waiter_keeps_creation_owned_then_reclaims_undelivered_stage():
    factory = _SlowChatFactory()
    manager, adapter = _chat_manager(factory, offline_timeout=0)
    opening = asyncio.create_task(adapter.open(user_id="slow", connection_id=object()))
    try:
        await asyncio.wait_for(factory.entered.wait(), 1)
        opening.cancel()
        await asyncio.sleep(0)
        assert not opening.done()
        with pytest.raises(RuntimeError, match="USER_INTERACTION_BUSY"):
            await manager.begin_user_data_reset("slow")
        factory.release.set()
        with pytest.raises(asyncio.CancelledError):
            await opening
        await _eventually(lambda: factory.created[0].closed)
        await manager._finalizations.close()
        assert not adapter._bindings
        assert not manager._chat_creations and not manager._stages
        token = await manager.begin_user_data_reset("slow")
        await manager.end_user_data_reset("slow", token)
    finally:
        factory.release.set()
        await asyncio.gather(opening, return_exceptions=True)
        await adapter.close()
        await manager.close()


@pytest.mark.asyncio
async def test_chat_creation_invalidated_by_reset_generation_closes_unpublished_context():
    factory = _SlowChatFactory()
    manager, adapter = _chat_manager(factory)
    opening = asyncio.create_task(adapter.open(user_id="slow", connection_id=object()))
    try:
        await asyncio.wait_for(factory.entered.wait(), 1)
        token = await manager._user_reset_fence.begin("slow")
        await manager._user_reset_fence.end("slow", token)
        factory.release.set()
        with pytest.raises(RuntimeError, match="USER_DATA_RESET_INVALIDATED_OPERATION"):
            await opening
        assert factory.created[0].closed
        assert not manager._stages and not manager._chat_creations
        assert not adapter._bindings
    finally:
        factory.release.set()
        await asyncio.gather(opening, return_exceptions=True)
        await adapter.close()
        await manager.close()


@pytest.mark.asyncio
async def test_call_retention_timer_is_manager_owned_and_old_deadline_cannot_end_reconnected_call():
    clock = _Clock()
    manager = make_stage_manager(
        adapter=WebSocketAdapter(),
        get_agent=lambda _: _agent(_TurnHandler()),
        get_context_factory=lambda _: ContextFactory(character_id="luotianyi", database=_ContextDatabase()),
        call_sessions=InMemoryCallSessionRepository(),
        realtime_speech_factory=FakeRealtimeSpeechSessionFactory(),
        call_output_sink=output_sink(_Transport()),
        wall_clock=clock.now,
        monotonic=clock.tick,
    )
    try:
        stage = await manager.try_to_get_stage(
            user_id="user", character_id="luotianyi", stage_type="call", client_request_id="retention"
        )
        await stage.start()
        await stage.apply_answer(
            d.AnswerCall(action_id="answer", call_id=stage._record.call_id, decision=CallAnswerDecision.ACCEPT)
        )
        await _eventually(lambda: stage.state is CallState.ACTIVE)
        await stage.disconnect()
        old_timer = manager._expiry[stage]
        old_deadline = stage._recovery_deadline
        assert old_timer not in stage.tasks
        clock.monotonic += 1
        assert await stage.reconnect()
        assert stage not in manager._expiry
        await asyncio.gather(old_timer, return_exceptions=True)
        assert old_timer.cancelled()
        await stage.disconnect()
        clock.monotonic += 2
        await stage.expire_retention(old_deadline)
        assert stage.state is CallState.RECONNECTING
        # 新计时尚未获得运行机会；推进到其期限后由 Manager 实际回收。
        clock.monotonic += 1
        await asyncio.wait_for(stage.wait_realtime_stopped(), 1)
        await stage.terminate()
        assert stage.snapshot.terminal.end_reason is CallEndReason.RECOVERY_TIMEOUT
        assert stage not in manager._expiry
        assert stage.call_id not in manager._call_stages
    finally:
        await manager.close()
