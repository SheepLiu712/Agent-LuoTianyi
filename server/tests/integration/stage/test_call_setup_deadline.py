"""从 Manager 公开接入验证总预算，不用新增参数缺失充当红灯。"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from support.aliyun_realtime_speech import FakeAliyunConnector, FakeAliyunWebSocket
from support.call_session_repository import InMemoryCallSessionRepository
from support.stage_manager import CallConversationStore

import src.domain.agent as d
from src.adapter.websocket.chat import WebSocketAdapter
from src.agent.context import ContextFactory
from src.agent.facade import Agent
from src.agent.handlers.action.call import AnswerCallHandler
from src.agent.handlers.action.call_settlement import FinalizeCallHandler
from src.agent.handlers.action.router import ActionRouter
from src.agent.handlers.stimulus.call import CallAnswerRequestedHandler, CallEndingHandler
from src.agent.handlers.stimulus.router import StimulusRouter
from src.agent.processing.omni_background import CallSessionPrompt
from src.agent.skills.cognitive.call_settlement import CallSummarySkill
from src.agent.skills.cognitive_maintenance import CognitiveMaintenanceSkill
from src.agent.skills.contracts import CharacterNarrative
from src.domain.call import CallEndReason, CallState
from src.domain.call.terminal import CallTerminated
from src.domain.stage.lifecycle import StageEndReason, StageInitializationFailed, StageShutdownFailed
from src.infrastructure.models.realtime_speech.config import AliyunRealtimeSpeechConfig
from src.infrastructure.models.realtime_speech.omni import QwenOmniSessionFactory
from src.stage import StageManager


class _ContextDatabase:
    """空用户资料/种子是存储端口替身；Context 与生命周期仍用真实实现。"""

    def get_user_description(self, _user_id):
        return ""

    def get_user_preferences(self, _user_id):
        return {}

    def get_call_conversation_seed_state(self, _user_id, *, character_id, requested_at):
        return {"summary": "", "conversations": []}


async def _flush_ready_tasks():
    # 只让就绪回调/真实 asyncio 定时器运行，不替换 wait_for/sleep/生产私有方法。
    for _ in range(200):
        await asyncio.sleep(0)


@pytest.mark.asyncio
@pytest.mark.parametrize("setup_timeout", [10.0, 30.0])
async def test_model_ready_at_fifteen_seconds_uses_manager_total_budget(monkeypatch, setup_timeout):
    """维护者示例：第15秒就绪，10秒超时；30秒不能被遗留10秒截断。"""
    loop = asyncio.get_running_loop()
    clock = {"now": loop.time()}
    began = clock["now"]
    monkeypatch.setattr(loop, "time", lambda: clock["now"])
    socket = FakeAliyunWebSocket(acknowledge_session=False)
    provider = QwenOmniSessionFactory(
        AliyunRealtimeSpeechConfig(
            api_key="offline",
            model="qwen3.5-omni-plus-realtime",
            endpoint="wss://provider.invalid/api-ws/v1/realtime",
            connect_timeout_seconds=10.0,
            session_timeout_seconds=10.0,
        ),
        connector=FakeAliyunConnector(socket),
    )
    manager, repository, outputs = _manager_for(provider, loop, clock, began, setup_timeout)
    stage = None
    try:
        await manager.initialize()
        stage = await manager.try_to_get_stage(
            user_id="user", character_id="luotianyi", stage_type="call", client_request_id="deadline-example"
        )
        await stage.set_connection_available(True)
        await socket.send_started.wait()
        await _flush_ready_tasks()

        clock["now"] = began + 10.25
        await _flush_ready_tasks()
        if setup_timeout == 10.0:
            await stage.terminate(StageEndReason.SHUTDOWN)
            terminal = next(output for output in outputs if isinstance(output, CallTerminated))
            assert terminal.end_reason is CallEndReason.SETUP_TIMEOUT
            assert repository.find_by_request("deadline-example").end_reason is CallEndReason.SETUP_TIMEOUT
        else:
            assert not stage.termination_requested, "30秒总预算不能被遗留10秒会话上限提前终止"
            clock["now"] = began + 15.0
            await socket.server_event({"type": "session.updated"})
            await stage.start()
            await _flush_ready_tasks()
            assert stage.state is CallState.ACTIVE
    finally:
        if stage is not None:
            await stage.terminate(StageEndReason.USER_REQUESTED)
        await manager.close()
        assert socket.closed


def _manager_for(provider, loop, clock, began, setup_timeout):
    maintenance = CognitiveMaintenanceSkill({}, llm_service=object(), memories={"luotianyi": object()})
    summary = CallSummarySkill({}, llm_service=object(), characters={})
    agent = Agent(
        character_id="luotianyi",
        omni_factory=provider,
        narrative=CharacterNarrative(name="洛天依", persona="虚拟歌手", speaking_style="自然"),
        omni_prompt=CallSessionPrompt("res/agent/prompts/realtime_call_prompt.json"),
        stimulus_router=StimulusRouter(
            (
                (d.StimulusKind.CALL_ANSWER_REQUESTED, CallAnswerRequestedHandler()),
                (d.StimulusKind.CALL_ENDING, CallEndingHandler()),
            )
        ),
        action_router=ActionRouter(
            (
                (d.ActionKind.ANSWER_CALL, AnswerCallHandler()),
                (d.ActionKind.FINALIZE_CALL, FinalizeCallHandler("luotianyi", maintenance, summary)),
            )
        ),
    )
    repository = InMemoryCallSessionRepository()
    outputs = []
    adapter = WebSocketAdapter()
    context_factory = ContextFactory(character_id="luotianyi", database=_ContextDatabase())

    async def receive(_call_id, output):
        outputs.append(output)

    manager = StageManager(
        get_agent=lambda _: agent,
        chat_output_sink=adapter.output_sink,
        detach_stage_binding=adapter.detach_stage_binding,
        get_context_factory=lambda _: context_factory,
        call_output_sink=receive,
        call_sessions=repository,
        conversation_service=CallConversationStore(),
        call_maintenance_batches=object(),
        realtime_speech_factory=provider,
        monotonic=loop.time,
        wall_clock=lambda: datetime(2026, 11, 17, tzinfo=timezone.utc) + timedelta(seconds=clock["now"] - began),
        config={"call_setup_timeout": setup_timeout},
    )
    adapter.initialize(manager)
    return manager, repository, outputs


class _GateSocket(FakeAliyunWebSocket):
    def __init__(self, *, close_failure=False, block_close=False, block_sends=False):
        super().__init__(block_sends=block_sends, acknowledge_session=False)
        self.close_failure = close_failure
        self.close_calls = 0
        self.release_close = asyncio.Event()
        if not block_close:
            self.release_close.set()

    async def close(self):
        self.close_calls += 1
        self.close_started.set()
        await self.release_close.wait()
        if self.close_failure:
            raise OSError("offline close failed")
        self.closed = True


async def _open_call(manager, request="deadline-example"):
    await manager.initialize()
    stage = await manager.try_to_get_stage(
        user_id="user", character_id="luotianyi", stage_type="call", client_request_id=request
    )
    await stage.set_connection_available(True)
    return stage


def _controlled_clock(monkeypatch):
    loop = asyncio.get_running_loop()
    clock = {"now": loop.time()}
    began = clock["now"]
    monkeypatch.setattr(loop, "time", lambda: clock["now"])
    return loop, clock, began


def _provider(socket, connector=None, close_timeout=5.0):
    return QwenOmniSessionFactory(
        AliyunRealtimeSpeechConfig(
            api_key="offline",
            model="qwen3.5-omni-plus-realtime",
            endpoint="wss://provider.invalid/api-ws/v1/realtime",
            close_timeout_seconds=close_timeout,
        ),
        connector=connector or FakeAliyunConnector(socket),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("close_failure", [False, True], ids=["slow-close", "failed-close"])
async def test_auth_failure_at_four_seconds_keeps_reason_and_cleanup_ownership(monkeypatch, close_failure):
    loop, clock, began = _controlled_clock(monkeypatch)
    socket = _GateSocket(close_failure=close_failure, block_close=not close_failure)
    manager, repository, outputs = _manager_for(_provider(socket, close_timeout=60), loop, clock, began, 30.0)
    stage = await _open_call(manager)
    try:
        await socket.send_started.wait()
        clock["now"] = began + 4.0
        await socket.server_event({"type": "error", "error": {"code": "invalid_api_key"}})
        await _flush_ready_tasks()
        await socket.close_started.wait()
        terminal = next(item for item in outputs if isinstance(item, CallTerminated))
        assert terminal.end_reason is CallEndReason.SYSTEM_FAILURE
        assert socket.close_calls == 1
        with pytest.raises(StageInitializationFailed) as failed:
            await stage.start()
        cause = failed.value
        reasons = []
        while cause is not None:
            reasons.append(str(cause))
            cause = cause.__cause__
        assert any("invalid_api_key" in reason for reason in reasons)
        with pytest.raises(RuntimeError, match="USER_INTERACTION_BUSY"):
            await manager.begin_user_data_reset("user")
        clock["now"] = began + 31.0
        await _flush_ready_tasks()
        assert terminal.end_reason is CallEndReason.SYSTEM_FAILURE
        socket.release_close.set()
        result = await stage.terminate(StageEndReason.USER_REQUESTED)
        assert result.resources_released is not close_failure
        assert bool(result.cleanup_error) is close_failure
        assert repository.find_by_request("deadline-example").end_reason is CallEndReason.SYSTEM_FAILURE
        assert socket.close_calls == 1
    finally:
        socket.release_close.set()
        if close_failure:
            with pytest.raises(StageShutdownFailed):
                await manager.close()
        else:
            await manager.close()


@pytest.mark.asyncio
async def test_connect_and_ready_share_remaining_budget_including_blocked_update_send(monkeypatch):
    loop, clock, began = _controlled_clock(monkeypatch)
    socket = _GateSocket(block_sends=True)
    connected = asyncio.Event()
    release_connect = asyncio.Event()

    async def connector(_url, *, open_timeout, **_transport_options):
        connected.set()
        await asyncio.wait_for(release_connect.wait(), open_timeout)
        return socket

    manager, _, outputs = _manager_for(_provider(socket, connector), loop, clock, began, 30.0)
    stage = await _open_call(manager)
    try:
        await connected.wait()
        clock["now"] = began + 15.0
        await _flush_ready_tasks()
        assert not stage.termination_requested
        release_connect.set()
        await socket.send_started.wait()
        clock["now"] = began + 29.0
        await _flush_ready_tasks()
        assert not stage.termination_requested
        clock["now"] = began + 30.25
        await _flush_ready_tasks()
        await stage.terminate(StageEndReason.SHUTDOWN)
        terminal = next(item for item in outputs if isinstance(item, CallTerminated))
        assert terminal.end_reason is CallEndReason.SETUP_TIMEOUT
        assert socket.close_calls == 1
    finally:
        release_connect.set()
        socket.release_sends.set()
        await manager.close()


@pytest.mark.asyncio
async def test_user_cancel_waits_for_late_connected_socket_and_closes_once(monkeypatch):
    loop, clock, began = _controlled_clock(monkeypatch)
    socket = _GateSocket()
    connecting, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def connector(_url, **_transport_options):
        connecting.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            await release.wait()
        return socket

    manager, _, outputs = _manager_for(_provider(socket, connector), loop, clock, began, 30.0)
    stage = await _open_call(manager)
    stop = None
    try:
        await connecting.wait()
        stop = asyncio.create_task(stage.terminate(StageEndReason.USER_REQUESTED))
        await cancelled.wait()
        await _flush_ready_tasks()
        assert not stop.done()
        terminal = next(item for item in outputs if isinstance(item, CallTerminated))
        assert terminal.end_reason is CallEndReason.USER_HANGUP
        release.set()
        result = await stop
        assert result.resources_released and socket.closed
        assert socket.close_calls == 1
        assert not any(getattr(item, "state", None) is CallState.ACTIVE for item in outputs)
    finally:
        release.set()
        if stop is not None:
            await stop
        await manager.close()
