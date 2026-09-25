"""Stage 的公开接入、调度、取消与生命周期行为。"""

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

import src.domain.agent as d
from src.adapter.websocket import WebSocketAdapter
from src.agent import Agent
from src.agent.handlers.stimulus.interaction import InteractionEndingHandler
from src.agent.handlers.stimulus.router import StimulusRouter
from src.domain.stage import StageState
from src.stage import ChatStage, StageManager
from src.web.websocket import WSMessage
from src.web.websocket.service import WebSocketConnection


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
    common = {
        "stimulus_id": str(uuid4()),
        "schema_version": 1,
        "occurred_at": datetime.now(timezone.utc),
        "source": d.StimulusSource.USER,
        "target_character_ids": ("luotianyi",),
        "user_id": "user",
        "ephemeral": False,
    }
    if cls is d.TextMessage:
        common.update(text="你好", client_msg_id=str(uuid4()))
    common.update(fields)
    return cls(**common)


def report(request, *, consumed=(), plans=()):
    pending = tuple(item.stimulus_id for item in request.interaction.pending_stimuli)
    prepared = None
    if isinstance(request.stimulus, (d.TextMessage, d.ImageMessage, d.VoiceMessage)):
        prepared = d.PreprocessedInput(
            stimulus_id=request.stimulus.stimulus_id,
            text=request.stimulus.text if isinstance(request.stimulus, d.TextMessage) else None,
        )
    return d.HandlingReport(
        request_id=request.request_id,
        trigger_stimulus_id=request.stimulus.stimulus_id,
        basis_interaction_revision=request.interaction.interaction_revision,
        request_status=d.HandlingRequestStatus.COMPLETED,
        considered_pending_stimulus_ids=pending,
        consumed_pending_stimulus_ids=tuple(i for i in pending if i in consumed),
        retained_pending_stimulus_ids=tuple(i for i in pending if i not in consumed),
        preprocessed_input=prepared,
        emitted_plan_ids=tuple(plans),
        error_code=None,
        retryable=False,
    )


def plan(request, *, ordinal=0, thinking=False):
    action = (
        d.StartThinking(action_id=str(uuid4()))
        if thinking
        else d.Say(
            action_id=str(uuid4()),
            content="你好",
            sound_content=None,
            prepared_audio_ref=None,
            tone=d.Tone(value="normal"),
            expression=None,
            delivery=d.OutputDelivery.CONVERSATION,
        )
    )
    return d.ActionPlan(
        plan_id=str(uuid4()),
        origin_request_id=request.request_id,
        plan_ordinal=ordinal,
        target_character_id="luotianyi",
        interaction_id=request.interaction.interaction_id,
        basis_interaction_revision=request.interaction.interaction_revision,
        source_stimulus_ids=(request.stimulus.stimulus_id,),
        actions=(action,),
    )


class RecordingAgent:
    def __init__(self, handle=None, realize=None):
        self.requests = asyncio.Queue()
        self.executions = asyncio.Queue()
        self.handle = handle
        self.realize = realize

    def is_handle_interruptible(self, interaction_id, request_id=None):
        return True

    def is_realize_interruptible(self, interaction_id):
        return False

    async def handle_stimulus(self, request, sink, *, context=None):
        self.requests.put_nowait(request)
        if self.handle is not None:
            return await self.handle(request, sink)
        return report(
            request,
            consumed=(
                tuple(s.stimulus_id for s in request.interaction.pending_stimuli)
                if isinstance(request.stimulus, d.InteractionDeadline)
                else ()
            ),
        )

    async def realize_action_plan(self, value, context, sink):
        self.executions.put_nowait((value, context, sink))
        if self.realize is not None:
            return await self.realize(value, context, sink)
        return SimpleNamespace(status=d.ExecutionStatus.COMPLETED, error_code=None)


async def take(queue):
    return await asyncio.wait_for(queue.get(), 1)


class StageContextFactory:
    def __init__(self, character_id="luotianyi"):
        self.character_id = character_id
        self.created = []

    async def create(self, interaction_id, *, user_id):
        context = SimpleNamespace(
            identity=SimpleNamespace(interaction_id=interaction_id, user_id=user_id, character_id=self.character_id),
            closed=False,
        )

        async def close():
            context.closed = True

        from src.agent.context import RecalledMemoryContext

        context.recalled_memory = RecalledMemoryContext()
        context.close = close
        from src.agent.context import ConversationSnapshot

        entries = []

        async def append(values):
            entries.extend(values)

        context.conversation = SimpleNamespace(
            append=append,
            entries=entries,
            read=lambda: ConversationSnapshot(entries=tuple(entries)),
        )
        self.created.append(context)
        return context


async def setup(agent=None, config=None):
    socket = Socket()
    connection = WebSocketConnection(socket, "user", "用户")
    adapter = WebSocketAdapter()
    agent = agent or RecordingAgent()
    stage = await ChatStage.create(
        user_id="user",
        character_id="luotianyi",
        agent=agent,
        adapter=adapter,
        config={"response_wait": 0.02, **(config or {})},
        context_factory=StageContextFactory(),
    )
    await adapter.bind(stage, connection)
    return stage, agent, adapter, connection, socket


async def cleanup(stage, adapter):
    await stage.terminate(d.InteractionEndingReason.SHUTDOWN)
    await adapter.disconnect(stage)


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
    owned_context = stage.context
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
    assert stage.context is owned_context and not owned_context.closed
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
    assert stage.state is StageState.TERMINATED and stage.context.closed
    await adapter.disconnect(stage)


@pytest.mark.asyncio
async def test_input_capacity_identity_and_inactive_output_rejection():
    stage, _, adapter, _, _ = await setup(config={"max_stimuli": 1})
    assert not stage.stimulus_input_sink.submit(stimulus(user_id="foreign"))
    assert stage.stimulus_input_sink.submit(stimulus())
    assert not stage.stimulus_input_sink.submit(stimulus())
    with pytest.raises(d.SinkRejectedError):
        await stage.agent_output_sink.emit(
            d.TextFinalOutput(
                interaction_id=stage.interaction_id,
                execution_id="unknown",
                action_id="unknown",
                sequence_no=0,
                delivery=d.OutputDelivery.CONVERSATION,
                text="hi",
            )
        )
    await cleanup(stage, adapter)


@pytest.mark.asyncio
async def test_manager_reconnect_old_disconnect_and_offline_expiry():
    adapter, agent = WebSocketAdapter(), RecordingAgent()
    manager = StageManager(
        get_context_factory=StageContextFactory,
        get_agent=lambda _: agent,
        adapter=adapter,
        config={"offline_timeout": 0.15},
    )
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
    assert await adapter.receive_event(
        new, WSMessage(event_type="user_text", client_msg_id="new", payload={"text": "你好"})
    )
    await take(agent.requests)
    await manager.close()
    assert stage.state is other.state is StageState.TERMINATED


@pytest.mark.asyncio
async def test_reconnect_during_ending_creates_new_interaction():
    ending_started, gate = asyncio.Event(), asyncio.Event()

    async def handle(request, sink):
        if (
            isinstance(request.stimulus, d.InteractionEnding)
            and request.stimulus.reason is d.InteractionEndingReason.USER_LEFT
        ):
            ending_started.set()
            await gate.wait()
        return report(request)

    adapter = WebSocketAdapter()
    manager = StageManager(
        get_context_factory=StageContextFactory,
        get_agent=lambda _: RecordingAgent(handle),
        adapter=adapter,
        config={"offline_timeout": 0},
    )
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
async def test_stage_releases_context_after_ending_handler():
    factory = StageContextFactory()
    adapter = WebSocketAdapter()
    entered, proceed = asyncio.Event(), asyncio.Event()

    class Ending(InteractionEndingHandler):
        async def handle(self, request, plans):
            assert not stage.context.closed
            entered.set()
            await proceed.wait()
            return await super().handle(request, plans)

    agent = Agent(
        character_id="luotianyi", stimulus_router=StimulusRouter([(d.StimulusKind.INTERACTION_ENDING, Ending())])
    )
    stage = await ChatStage.create(
        user_id="user", character_id="luotianyi", agent=agent, adapter=adapter, context_factory=factory
    )
    termination = asyncio.create_task(stage.terminate(d.InteractionEndingReason.USER_LEFT))
    await entered.wait()
    assert not stage.context.closed
    proceed.set()
    result = await termination
    assert result.error is None and stage.context.closed
    assert len(factory.created) == 1


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
        await sink.emit(
            d.MessageEndOutput(
                interaction_id=context.interaction_id,
                execution_id=context.execution_id,
                action_id=value.actions[0].action_id,
                sequence_no=0,
                delivery=d.OutputDelivery.CONVERSATION,
                status=d.MessageEndStatus.FAILED,
                error_code=d.AudioErrorCode.EMPTY_AUDIO,
            )
        )
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
    from src.agent.skills.expression.prepared_speech import PreparedSpeechCatalog

    data = io.BytesIO()
    with wave.open(data, "wb") as wav:
        wav.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        wav.writeframes(b"\x00\x01" * 120)
    (tmp_path / "hello.wav").write_bytes(data.getvalue())
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "name": "hello",
                    "audio_path": "hello.wav",
                    "text": "你好",
                    "expression": "normal",
                }
            ]
        ),
        encoding="utf-8",
    )

    class TextHandler:
        async def handle(self, request, plans):
            if isinstance(request.stimulus, d.TextMessage):
                return report(request)
            action = replace(plan(request).actions[0], prepared_audio_ref=d.MediaRef(media_id="hello"))
            accepted = await plans.emit(
                ActionPlanDraft(source_stimulus_ids=(request.stimulus.stimulus_id,), actions=(action,))
            )
            return report(
                request,
                consumed=tuple(s.stimulus_id for s in request.interaction.pending_stimuli),
                plans=(accepted.plan_id,),
            )

    agent = Agent(
        character_id="luotianyi",
        stimulus_router=StimulusRouter(
            [
                (d.StimulusKind.TEXT_MESSAGE, TextHandler()),
                (d.StimulusKind.INTERACTION_DEADLINE, TextHandler()),
                (d.StimulusKind.INTERACTION_ENDING, InteractionEndingHandler()),
            ]
        ),
        action_router=ActionRouter(
            [
                (
                    d.ActionKind.SAY,
                    SayHandler(
                        "luotianyi", object(), PreparedSpeechCatalog({"luotianyi": {"manifest": str(manifest)}})
                    ),
                )
            ]
        ),
    )
    stage, _, adapter, connection, socket = await setup(agent)
    assert await adapter.receive_event(
        connection, WSMessage(event_type="user_text", client_msg_id="one", payload={"text": "你好"})
    )

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
async def test_stage_construction_failure_closes_created_context():
    factory = StageContextFactory()
    with pytest.raises(ValueError):
        await ChatStage.create(
            user_id="user",
            character_id="luotianyi",
            agent=RecordingAgent(),
            adapter=WebSocketAdapter(),
            context_factory=factory,
            config={"max_stimuli": 0},
        )
    assert len(factory.created) == 1 and factory.created[0].closed
