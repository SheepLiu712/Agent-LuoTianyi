"""Stage 的公开接入、调度、取消与生命周期行为。"""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

import src.domain.agent as d
from src.domain.stage import StageState
from src.adapter.websocket import WebSocketAdapter
from src.stage import ChatStage, StageManager
from src.agent import Agent
from src.agent.context import ContextFactory
from src.agent.handlers.stimulus.interaction import InteractionEndingHandler
from src.agent.handlers.stimulus.router import StimulusRouter
from src.system.user_interface.types import WSMessage
from src.system.user_interface.websocket_service import WebSocketConnection


class Socket:
    def __init__(self):
        self.events = []
        self.gate = None
        self.entered = asyncio.Event()

    async def send_json(self, event):
        self.entered.set()
        if self.gate is not None:
            await self.gate.wait()
        self.events.append(event)


def stimulus(cls=d.TextMessage, **fields):
    common = dict(stimulus_id=str(uuid4()), schema_version=1, occurred_at=datetime.now(timezone.utc),
                  source=d.StimulusSource.USER, target_character_ids=("luotianyi",), user_id="user", ephemeral=False)
    if cls is d.TextMessage:
        common.update(text="你好", client_msg_id=str(uuid4()))
    common.update(fields)
    return cls(**common)


def report(request, *, consumed=(), plans=(), reconsider_at=None):
    pending = tuple(item.stimulus_id for item in request.interaction.pending_stimuli)
    return d.HandlingReport(request_id=request.request_id, trigger_stimulus_id=request.stimulus.stimulus_id,
        basis_interaction_revision=request.interaction.interaction_revision,
        request_status=d.HandlingRequestStatus.COMPLETED, considered_pending_stimulus_ids=pending,
        consumed_pending_stimulus_ids=tuple(i for i in pending if i in consumed),
        retained_pending_stimulus_ids=tuple(i for i in pending if i not in consumed),
        emitted_plan_ids=tuple(plans), reconsider_at=reconsider_at, error_code=None, retryable=False)


def plan(request, *, ordinal=0, thinking=False):
    action = d.StartThinking(action_id=str(uuid4())) if thinking else d.Say(
        action_id=str(uuid4()), content="你好", sound_content=None, prepared_audio_ref=None,
        tone=d.Tone(value="normal"), expression=None, delivery=d.OutputDelivery.CONVERSATION)
    return d.ActionPlan(plan_id=str(uuid4()), origin_request_id=request.request_id, plan_ordinal=ordinal,
        target_character_id="luotianyi", interaction_id=request.interaction.interaction_id,
        basis_interaction_revision=request.interaction.interaction_revision,
        source_stimulus_ids=(request.stimulus.stimulus_id,), actions=(action,))


class RecordingAgent:
    def __init__(self, handle=None, realize=None):
        self.requests = asyncio.Queue()
        self.executions = asyncio.Queue()
        self.handle = handle
        self.realize = realize

    def is_handle_interruptible(self, interaction_id):
        return True

    def is_realize_interruptible(self, interaction_id):
        return False

    async def handle_stimulus(self, request, sink):
        self.requests.put_nowait(request)
        if self.handle is not None:
            return await self.handle(request, sink)
        return report(request)

    async def realize_action_plan(self, value, context, sink):
        self.executions.put_nowait((value, context, sink))
        if self.realize is not None:
            return await self.realize(value, context, sink)
        return SimpleNamespace(status=d.ExecutionStatus.COMPLETED, error_code=None)


async def take(queue):
    return await asyncio.wait_for(queue.get(), 1)


async def setup(agent=None, config=None):
    socket = Socket()
    connection = WebSocketConnection(socket, "user", "用户")
    adapter = WebSocketAdapter()
    agent = agent or RecordingAgent()
    stage = ChatStage(user_id="user", character_id="luotianyi", agent=agent, adapter=adapter, config=config)
    await adapter.bind(stage, connection)
    return stage, agent, adapter, connection, socket


async def cleanup(stage, adapter):
    await stage.terminate(d.InteractionEndingReason.SHUTDOWN)
    await adapter.disconnect(stage)


@pytest.mark.asyncio
async def test_pending_consumption_typing_and_snapshot_revision():
    async def handle(request, sink):
        consumed = () if isinstance(request.stimulus, d.TextMessage) else tuple(s.stimulus_id for s in request.interaction.pending_stimuli)
        return report(request, consumed=consumed)
    stage, agent, adapter, _, _ = await setup(RecordingAgent(handle))
    a = stimulus()
    assert stage.stimulus_input_sink.submit(a)
    first = await take(agent.requests)
    typing = stimulus(d.UserTyping, text_length=4)
    assert stage.stimulus_input_sink.submit(typing)
    second = await take(agent.requests)
    assert second.interaction.pending_stimuli == (a,)
    assert second.interaction.interaction_revision > first.interaction.interaction_revision
    b = stimulus()
    stage.stimulus_input_sink.submit(b)
    third = await take(agent.requests)
    assert third.interaction.pending_stimuli == (b,)
    await cleanup(stage, adapter)


@pytest.mark.asyncio
async def test_new_stimulus_cancels_handle_without_losing_new_pending():
    gate = asyncio.Event()
    async def handle(request, sink):
        if request.stimulus is a:
            await gate.wait()
        return report(request, consumed=(request.stimulus.stimulus_id,))
    a, b = stimulus(), stimulus()
    stage, agent, adapter, _, _ = await setup(RecordingAgent(handle))
    stage.stimulus_input_sink.submit(a)
    first = await take(agent.requests)
    stage.stimulus_input_sink.submit(b)
    assert first.cancellation.reason is d.CancellationReason.SUPERSEDED
    assert agent.requests.empty()
    gate.set()
    second = await take(agent.requests)
    assert second.interaction.pending_stimuli == (b,)
    await cleanup(stage, adapter)


@pytest.mark.asyncio
async def test_deadline_is_internal_stimulus_and_not_pending():
    async def handle(request, sink):
        deadline = datetime.now(timezone.utc) + timedelta(milliseconds=10) if isinstance(request.stimulus, d.TextMessage) else None
        return report(request, reconsider_at=deadline)
    stage, agent, adapter, _, _ = await setup(RecordingAgent(handle))
    a = stimulus()
    stage.stimulus_input_sink.submit(a)
    await take(agent.requests)
    due = await take(agent.requests)
    assert isinstance(due.stimulus, d.InteractionDeadline)
    assert due.stimulus.source is d.StimulusSource.STAGE
    assert due.interaction.pending_stimuli == (a,)
    await cleanup(stage, adapter)


@pytest.mark.asyncio
async def test_thinking_is_stage_control_and_realize_is_serial_without_network_wait():
    completed = asyncio.Queue()
    first_gate = asyncio.Event()
    handles = 0
    realizes = 0
    async def handle(request, sink):
        nonlocal handles
        if isinstance(request.stimulus, d.InteractionEnding):
            return report(request)
        handles += 1
        thinking, say = plan(request, thinking=True), plan(request, ordinal=1)
        await sink.emit(thinking)
        await sink.emit(say)
        return report(request, consumed=(request.stimulus.stimulus_id,), plans=(thinking.plan_id, say.plan_id))
    async def realize(value, context, sink):
        nonlocal realizes
        realizes += 1
        if realizes == 1:
            await first_gate.wait()
        fields = dict(interaction_id=context.interaction_id, execution_id=context.execution_id,
                      action_id=value.actions[0].action_id, delivery=d.OutputDelivery.CONVERSATION)
        await sink.emit(d.TextFinalOutput(sequence_no=0, text="你好", **fields))
        await sink.emit(d.MessageEndOutput(sequence_no=1, status=d.MessageEndStatus.COMPLETED, error_code=None, **fields))
        completed.put_nowait(value.plan_id)
        return SimpleNamespace(status=d.ExecutionStatus.COMPLETED, error_code=None)
    stage, agent, adapter, _, socket = await setup(RecordingAgent(handle, realize))
    socket.gate = asyncio.Event()
    stage.stimulus_input_sink.submit(stimulus())
    first = await take(agent.executions)
    stage.stimulus_input_sink.submit(stimulus())
    await take(agent.requests)
    await take(agent.requests)
    assert handles == 2 and realizes == 1
    assert not first[1].cancellation.is_cancelled
    first_gate.set()
    await take(completed)
    await take(completed)
    assert realizes == 2 and not socket.events
    assert (await take(agent.executions))[2] is first[2] is stage.agent_output_sink
    socket.gate.set()
    await cleanup(stage, adapter)
    assert any(p["type"] == "agent_state_changed" and p["payload"]["state"] == "thinking" for p in socket.events)


@pytest.mark.asyncio
async def test_disconnect_waits_agent_cleanup_and_reconnect_reuses_sink():
    cleanup_entered, cleanup_gate = asyncio.Event(), asyncio.Event()
    async def handle(request, sink):
        if isinstance(request.stimulus, d.InteractionEnding):
            return report(request)
        value = plan(request)
        await sink.emit(value)
        return report(request, plans=(value.plan_id,))
    async def realize(value, context, sink):
        try:
            await asyncio.Event().wait()
        finally:
            cleanup_entered.set()
            await cleanup_gate.wait()
    stage, agent, adapter, old, _ = await setup(RecordingAgent(handle, realize))
    sink = stage.agent_output_sink
    stage.stimulus_input_sink.submit(stimulus())
    _, context, _ = await take(agent.executions)
    disconnect = asyncio.create_task(adapter.disconnect(stage, old))
    await cleanup_entered.wait()
    assert not disconnect.done() and context.cancellation.reason is d.CancellationReason.NO_LONGER_NEEDED
    cleanup_gate.set()
    await disconnect
    assert stage.state is StageState.OFFLINE
    assert not stage.stimulus_input_sink.submit(stimulus())
    await adapter.bind(stage, WebSocketConnection(Socket(), "user", "用户"))
    assert stage.agent_output_sink is sink and stage.state is StageState.ONLINE
    await cleanup(stage, adapter)


@pytest.mark.asyncio
async def test_ending_fresh_token_and_rejection_after_termination():
    stage, agent, adapter, _, _ = await setup()
    stage.stimulus_input_sink.submit(stimulus())
    await take(agent.requests)
    result = await stage.terminate(d.InteractionEndingReason.USER_LEFT)
    ending = await take(agent.requests)
    assert isinstance(ending.stimulus, d.InteractionEnding)
    assert ending.stimulus.reason is d.InteractionEndingReason.USER_LEFT
    assert not ending.cancellation.is_cancelled and result.error is None
    assert ending.interaction.connection_state is d.ConnectionState.CONNECTED
    with pytest.raises(d.InvalidHandleInputError):
        replace(ending.interaction, pending_stimuli=(ending.stimulus,))
    assert await stage.terminate(d.InteractionEndingReason.SHUTDOWN) is result
    assert not stage.stimulus_input_sink.submit(stimulus())
    with pytest.raises(ValueError):
        await adapter.bind(stage, WebSocketConnection(Socket(), "user", "用户"))
    await adapter.disconnect(stage)


@pytest.mark.asyncio
async def test_ending_timeout_releases_stage():
    async def handle(request, sink):
        await asyncio.Event().wait()
    stage, _, adapter, _, _ = await setup(RecordingAgent(handle), {"termination_timeout": 0.01})
    result = await stage.terminate(d.InteractionEndingReason.USER_LEFT)
    assert result.error == "interaction ending timed out"
    assert stage.state is StageState.TERMINATED
    await adapter.disconnect(stage)


@pytest.mark.asyncio
async def test_input_capacity_identity_and_inactive_output_rejection():
    stage, _, adapter, _, _ = await setup(config={"max_stimuli": 1})
    assert not stage.stimulus_input_sink.submit(stimulus(user_id="foreign"))
    assert stage.stimulus_input_sink.submit(stimulus())
    assert not stage.stimulus_input_sink.submit(stimulus())
    with pytest.raises(d.SinkRejectedError):
        await stage.agent_output_sink.emit(d.TextFinalOutput(interaction_id=stage.interaction_id,
            execution_id="unknown", action_id="unknown", sequence_no=0, delivery=d.OutputDelivery.CONVERSATION, text="hi"))
    await cleanup(stage, adapter)


@pytest.mark.asyncio
async def test_manager_reconnect_old_disconnect_and_offline_expiry():
    adapter, agent = WebSocketAdapter(), RecordingAgent()
    manager = StageManager(get_agent=lambda _: agent, adapter=adapter, config={"offline_timeout": 0.15})
    old = WebSocketConnection(Socket(), "user", "用户")
    stage = await manager.connect(old, "luotianyi")
    other = await manager.connect(old, "miku")
    await manager.disconnect(old)
    new = WebSocketConnection(Socket(), "user", "用户")
    assert await manager.connect(new, "luotianyi") is stage
    await manager.disconnect(old)
    assert stage.state is StageState.ONLINE
    ending = await take(agent.requests)
    assert ending.interaction.interaction_id == other.interaction_id
    assert isinstance(ending.stimulus, d.InteractionEnding)
    assert adapter.receive_event(new, WSMessage(event_type="user_text", client_msg_id="new", payload={"text": "你好"}))
    await take(agent.requests)
    await manager.close()
    assert stage.state is other.state is StageState.TERMINATED


@pytest.mark.asyncio
async def test_reconnect_during_ending_creates_new_interaction():
    ending_started, gate = asyncio.Event(), asyncio.Event()
    async def handle(request, sink):
        if isinstance(request.stimulus, d.InteractionEnding) and request.stimulus.reason is d.InteractionEndingReason.USER_LEFT:
            ending_started.set()
            await gate.wait()
        return report(request)
    adapter = WebSocketAdapter()
    manager = StageManager(get_agent=lambda _: RecordingAgent(handle), adapter=adapter, config={"offline_timeout": 0})
    old = WebSocketConnection(Socket(), "user", "用户")
    stage = await manager.connect(old, "luotianyi")
    await manager.disconnect(old)
    await asyncio.wait_for(ending_started.wait(), 1)
    new = await manager.connect(WebSocketConnection(Socket(), "user", "用户"), "luotianyi")
    assert new is not stage and new.interaction_id != stage.interaction_id
    gate.set()
    await manager.close()
    assert stage.state is new.state is StageState.TERMINATED


@pytest.mark.asyncio
async def test_real_agent_ending_handler_releases_existing_context():
    factory = ContextFactory(character_id="luotianyi", database=object())
    released = []
    class Context:
        identity = SimpleNamespace(user_id="user")
        async def close(self):
            released.append(True)
    adapter = WebSocketAdapter()
    agent = Agent(character_id="luotianyi", stimulus_router=StimulusRouter([
        (d.StimulusKind.INTERACTION_ENDING, InteractionEndingHandler(factory))]))
    stage = ChatStage(user_id="user", character_id="luotianyi", agent=agent, adapter=adapter)
    factory._contexts[stage.interaction_id] = Context()
    result = await stage.terminate(d.InteractionEndingReason.USER_LEFT)
    assert result.error is None and released == [True]
    assert stage.interaction_id not in factory._contexts


@pytest.mark.asyncio
async def test_failed_terminal_is_preserved_instead_of_becoming_cancellation():
    done = asyncio.Event()
    async def handle(request, sink):
        if isinstance(request.stimulus, d.InteractionEnding):
            return report(request)
        value = plan(request)
        await sink.emit(value)
        return report(request, plans=(value.plan_id,))
    async def realize(value, context, sink):
        await sink.emit(d.MessageEndOutput(interaction_id=context.interaction_id, execution_id=context.execution_id,
            action_id=value.actions[0].action_id, sequence_no=0, delivery=d.OutputDelivery.CONVERSATION,
            status=d.MessageEndStatus.FAILED, error_code=d.AudioErrorCode.EMPTY_AUDIO))
        done.set()
        return SimpleNamespace(status=d.ExecutionStatus.FAILED, error_code=d.ExecutionErrorCode.AUDIO_EMPTY)
    stage, _, adapter, _, socket = await setup(RecordingAgent(handle, realize))
    stage.stimulus_input_sink.submit(stimulus())
    await asyncio.wait_for(done.wait(), 1)
    # 状态包也会到达 socket，等待业务终止包而非某个调度 tick。
    async def terminal():
        while not any(p["type"] == "agent_message" for p in socket.events):
            await asyncio.sleep(0)
    await asyncio.wait_for(terminal(), 1)
    assert next(p["payload"]["error_code"] for p in socket.events if p["type"] == "agent_message") == "TTS_EMPTY"
    await cleanup(stage, adapter)


@pytest.mark.asyncio
async def test_real_adapter_stage_agent_prepared_say_chain(tmp_path):
    import base64
    import io
    import json
    import wave
    from src.agent.handlers.action.router import ActionRouter
    from src.agent.handlers.action.say import SayHandler
    from src.agent.processing.plan_emitter import ActionPlanDraft
    from src.resources.prepared_speech import PreparedSpeechResources

    data = io.BytesIO()
    with wave.open(data, "wb") as wav:
        wav.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        wav.writeframes(b"\x00\x01" * 120)
    (tmp_path / "hello.wav").write_bytes(data.getvalue())
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([dict(name="hello", audio_path="hello.wav", text="你好", expression="normal")]), encoding="utf-8")
    class TextHandler:
        async def handle(self, request, plans):
            action = replace(plan(request).actions[0], prepared_audio_ref=d.MediaRef(media_id="hello"))
            accepted = await plans.emit(ActionPlanDraft(source_stimulus_ids=(request.stimulus.stimulus_id,), actions=(action,)))
            return report(request, consumed=(request.stimulus.stimulus_id,), plans=(accepted.plan_id,))
    agent = Agent(character_id="luotianyi", stimulus_router=StimulusRouter([
        (d.StimulusKind.TEXT_MESSAGE, TextHandler()),
        (d.StimulusKind.INTERACTION_ENDING, InteractionEndingHandler(ContextFactory(character_id="luotianyi", database=object()))),
    ]), action_router=ActionRouter([(d.ActionKind.SAY, SayHandler("luotianyi", object(), PreparedSpeechResources({"manifest": str(manifest)})))]))
    stage, _, adapter, connection, socket = await setup(agent)
    assert adapter.receive_event(connection, WSMessage(event_type="user_text", client_msg_id="one", payload={"text": "你好"}))
    async def terminal():
        while not any(p["type"] == "agent_message" and p["payload"]["is_final_package"] for p in socket.events):
            await asyncio.sleep(0)
    await asyncio.wait_for(terminal(), 2)
    packets = [p["payload"] for p in socket.events if p["type"] == "agent_message"]
    assert b"".join(base64.b64decode(p["audio"]) for p in packets) == data.getvalue()
    assert [p["packet_sequence"] for p in packets] == list(range(len(packets)))
    assert packets[-1]["is_final_package"] and packets[0]["text"] == "你好"
    await cleanup(stage, adapter)


@pytest.mark.asyncio
async def test_typing_invalidates_extraction_without_cancelling_llm_or_losing_pending():
    entered, finish = asyncio.Event(), asyncio.Event()
    requests = asyncio.Queue()
    class Handler:
        async def handle(self, req, plans):
            requests.put_nowait(req)
            if isinstance(req.stimulus, d.TextMessage):
                plans.set_interruptible(True)
                entered.set()
                await finish.wait()
                return report(req, consumed=(req.stimulus.stimulus_id,))
            return report(req)
    agent = Agent(character_id="luotianyi", stimulus_router=StimulusRouter([
        (kind, Handler()) for kind in (d.StimulusKind.TEXT_MESSAGE, d.StimulusKind.USER_TYPING, d.StimulusKind.INTERACTION_ENDING)]))
    stage, _, adapter, _, _ = await setup(agent)
    a = stimulus()
    stage.stimulus_input_sink.submit(a)
    await entered.wait()
    first = await take(requests)
    typing = stimulus(d.UserTyping, text_length=3)
    stage.stimulus_input_sink.submit(typing)
    assert first.cancellation.reason is d.CancellationReason.SUPERSEDED
    assert requests.empty()  # LLM 尚未完成，下一次 handle 尚未进入。
    finish.set()
    second = await take(requests)
    assert second.interaction.pending_stimuli == (a,)
    assert second.interaction.response_deadline == typing.occurred_at + timedelta(seconds=10)
    await cleanup(stage, adapter)


@pytest.mark.asyncio
async def test_typing_and_new_content_do_not_interrupt_reply_generation_or_invalidate_its_plan():
    from src.agent.handlers.action.router import ActionRouter
    from src.agent.processing.plan_emitter import ActionPlanDraft
    entered, finish, executed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    requests = asyncio.Queue()
    a = stimulus()
    class Handler:
        async def handle(self, req, plans):
            requests.put_nowait(req)
            if req.stimulus is not a:
                return report(req)
            plans.set_interruptible(False)
            entered.set()
            await finish.wait()
            accepted = await plans.emit(ActionPlanDraft(source_stimulus_ids=(a.stimulus_id,), actions=plan(req).actions))
            return report(req, consumed=(a.stimulus_id,), plans=(accepted.plan_id,))
    class ActionHandler:
        async def realize(self, action, context, outputs):
            assert not agent.is_realize_interruptible(context.interaction_id)
            executed.set()
            return d.ActionResult(action_id=action.action_id, status=d.ActionExecutionStatus.COMPLETED,
                error_code=None, irreversible_effect_committed=False, effect_ref=None)
    agent = Agent(character_id="luotianyi", stimulus_router=StimulusRouter([
        (kind, Handler()) for kind in (d.StimulusKind.TEXT_MESSAGE, d.StimulusKind.USER_TYPING, d.StimulusKind.INTERACTION_ENDING)]),
        action_router=ActionRouter([(d.ActionKind.SAY, ActionHandler())]))
    stage, _, adapter, _, _ = await setup(agent)
    stage.stimulus_input_sink.submit(a)
    await entered.wait()
    first = await take(requests)
    stage.stimulus_input_sink.submit(stimulus(d.UserTyping, text_length=4))
    b = stimulus()
    stage.stimulus_input_sink.submit(b)
    assert not first.cancellation.is_cancelled
    finish.set()
    await asyncio.wait_for(executed.wait(), 1)
    second = await take(requests)
    assert second.interaction.pending_stimuli == (b,)
    await cleanup(stage, adapter)


@pytest.mark.asyncio
@pytest.mark.parametrize("cls,fields,interrupts,wait", [
    (d.UserTyping, {"text_length": 0}, False, 0),
    (d.UserTyping, {"text_length": 1}, True, 10),
    (d.ImageSelectionOpened, {}, True, 60),
    (d.ImageSelectionClosed, {}, True, 1),
    (d.InteractionDeadline, {}, False, None),
])
async def test_waiting_signals_preserve_legacy_interruption_rules(cls, fields, interrupts, wait):
    gate = asyncio.Event()
    a = stimulus()
    async def handle(req, sink):
        if req.stimulus is a:
            await gate.wait()
        return report(req)
    stage, agent, adapter, _, _ = await setup(RecordingAgent(handle))
    stage.stimulus_input_sink.submit(a)
    first = await take(agent.requests)
    signal = stimulus(cls, **fields)
    stage.stimulus_input_sink.submit(signal)
    assert first.cancellation.is_cancelled is interrupts
    gate.set()
    second = await take(agent.requests)
    if wait is not None:
        assert second.interaction.response_deadline == signal.occurred_at + timedelta(seconds=wait)
    await cleanup(stage, adapter)


@pytest.mark.asyncio
@pytest.mark.parametrize("allowed", [False, True])
async def test_stage_queries_realize_permission_separately(allowed):
    finish = asyncio.Event()
    async def handle(req, sink):
        if isinstance(req.stimulus, d.TextMessage):
            value = plan(req)
            await sink.emit(value)
            return report(req, plans=(value.plan_id,))
        return report(req)
    async def realize(value, context, sink):
        await finish.wait()
        return SimpleNamespace(status=d.ExecutionStatus.CANCELLED if context.cancellation.is_cancelled
                               else d.ExecutionStatus.COMPLETED, error_code=None)
    class AgentWithPermission(RecordingAgent):
        def is_realize_interruptible(self, interaction_id):
            return allowed
    stage, agent, adapter, _, _ = await setup(AgentWithPermission(handle, realize))
    stage.stimulus_input_sink.submit(stimulus())
    _, context, _ = await take(agent.executions)
    stage.stimulus_input_sink.submit(stimulus(d.UserTyping, text_length=2))
    assert context.cancellation.is_cancelled is allowed
    finish.set()
    await cleanup(stage, adapter)
