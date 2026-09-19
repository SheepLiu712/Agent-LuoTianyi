"""ChatStage 测试共用的公开入口装配与领域样例。"""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import src.domain.agent as d
from src.adapter.websocket import WebSocketAdapter
from src.agent.context import ConversationSnapshot, RecalledMemoryContext, UserContextSnapshot
from src.stage import ChatStage
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
        consumed_pending_stimulus_ids=tuple(item for item in pending if item in consumed),
        retained_pending_stimulus_ids=tuple(item for item in pending if item not in consumed),
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
        consumed = (
            tuple(item.stimulus_id for item in request.interaction.pending_stimuli)
            if isinstance(request.stimulus, d.InteractionDeadline)
            else ()
        )
        return report(request, consumed=consumed)

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
            identity=SimpleNamespace(
                interaction_id=interaction_id,
                user_id=user_id,
                character_id=self.character_id,
            ),
            closed=False,
        )

        async def close():
            context.closed = True

        entries = []

        async def append(values):
            entries.extend(values)

        context.recalled_memory = RecalledMemoryContext()
        context.user = SimpleNamespace(read=UserContextSnapshot)
        context.close = close
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
