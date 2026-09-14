"""长期 WorldStage 的事实结算、计划串行与关闭行为。"""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

import src.domain.agent as d
from src.agent.context import RecalledMemoryContext
from src.domain.stage import StageState
from src.stage import NoChannelOutputSink, WorldStage


def world_observation(*, stimulus_id: str | None = None, revision: int = 1) -> d.WorldObservation:
    return d.WorldObservation(
        stimulus_id=stimulus_id or str(uuid4()), schema_version=1,
        occurred_at=datetime.now(timezone.utc), source=d.StimulusSource.WORLD,
        target_character_ids=("luotianyi",), user_id=None, ephemeral=False,
        observation_kind=d.WorldObservationKind(value="weather"),
        fact=d.WorldFact(fact_id=str(uuid4()), summary="晴朗"), evidence_refs=(),
        world_revision=revision,
    )


def handling_report(request: d.HandleStimulusRequest, *, plans: tuple[str, ...] = ()) -> d.HandlingReport:
    pending = tuple(item.stimulus_id for item in request.interaction.pending_stimuli)
    consumed = (request.stimulus.stimulus_id,)
    return d.HandlingReport(
        request_id=request.request_id, trigger_stimulus_id=request.stimulus.stimulus_id,
        basis_interaction_revision=request.interaction.interaction_revision,
        request_status=d.HandlingRequestStatus.COMPLETED,
        considered_pending_stimulus_ids=pending, consumed_pending_stimulus_ids=consumed,
        retained_pending_stimulus_ids=tuple(item for item in pending if item not in consumed),
        emitted_plan_ids=plans, error_code=None, retryable=False,
    )


def action_plan(request: d.HandleStimulusRequest, ordinal: int = 0) -> d.ActionPlan:
    return d.ActionPlan(
        plan_id=str(uuid4()), origin_request_id=request.request_id, plan_ordinal=ordinal,
        target_character_id="luotianyi", interaction_id=request.interaction.interaction_id,
        basis_interaction_revision=request.interaction.interaction_revision,
        source_stimulus_ids=(request.stimulus.stimulus_id,),
        actions=(d.Say(action_id=str(uuid4()), content="你好", sound_content=None,
                       prepared_audio_ref=None, tone=d.Tone(value="normal"), expression=None,
                       delivery=d.OutputDelivery.CONVERSATION),),
    )


class ContextFactory:
    def __init__(self) -> None:
        self.created = []

    async def create(self, interaction_id: str, *, user_id: str | None):
        context = SimpleNamespace(
            identity=SimpleNamespace(interaction_id=interaction_id, user_id=user_id,
                                     character_id="luotianyi"),
            recalled_memory=RecalledMemoryContext(), closed=False,
        )

        async def close() -> None:
            context.closed = True

        context.close = close
        self.created.append(context)
        return context


class RecordingAgent:
    def __init__(self) -> None:
        self.requests: asyncio.Queue[d.HandleStimulusRequest] = asyncio.Queue()
        self.executions = []
        self.handle_gate: asyncio.Event | None = None
        self.realize_gate: asyncio.Event | None = None
        self.active_realizations = 0
        self.max_active_realizations = 0

    async def handle_stimulus(self, request, sink, *, context=None):
        self.requests.put_nowait(request)
        if self.handle_gate is not None:
            await self.handle_gate.wait()
        return handling_report(request)

    async def realize_action_plan(self, plan, context, sink):
        self.executions.append((plan, context, sink))
        self.active_realizations += 1
        self.max_active_realizations = max(self.max_active_realizations, self.active_realizations)
        try:
            if self.realize_gate is not None:
                await self.realize_gate.wait()
            return SimpleNamespace(status=d.ExecutionStatus.COMPLETED, error_code=None)
        finally:
            self.active_realizations -= 1


async def create_stage(agent: RecordingAgent | None = None):
    factory = ContextFactory()
    actual_agent = agent or RecordingAgent()
    stage = await WorldStage.create(
        character_id="luotianyi", world_id="default", agent=actual_agent,
        context_factory=factory,
    )
    return stage, actual_agent, factory


@pytest.mark.asyncio
async def test_world_facts_keep_order_and_settle_by_stimulus_id():
    agent = RecordingAgent()
    agent.handle_gate = asyncio.Event()
    stage, _, _ = await create_stage(agent)
    first, second = world_observation(revision=4), world_observation(revision=5)

    assert await stage.fact_sink.submit(first)
    assert await stage.fact_sink.submit(second)
    first_request = await asyncio.wait_for(agent.requests.get(), 1)
    second_request = await asyncio.wait_for(agent.requests.get(), 1)

    assert tuple(item.stimulus_id for item in second_request.interaction.pending_stimuli) == (
        first.stimulus_id, second.stimulus_id,
    )
    assert second_request.interaction.world_revision == 5
    agent.handle_gate.set()
    await stage.wait_idle()
    assert stage.pending_stimuli == ()
    assert first_request.interaction.interaction_revision < second_request.interaction.interaction_revision
    await stage.close()


@pytest.mark.asyncio
async def test_stale_handle_plan_is_rejected_after_new_fact_revision():
    emitted = asyncio.Event()
    release = asyncio.Event()

    class StaleAgent(RecordingAgent):
        async def handle_stimulus(self, request, sink, *, context=None):
            self.requests.put_nowait(request)
            if request.stimulus.stimulus_id == first.stimulus_id:
                emitted.set()
                await release.wait()
                with pytest.raises(d.SinkRejectedError) as error:
                    await sink.emit(action_plan(request))
                assert error.value.code is d.SinkRejectionCode.STALE_INTERACTION
            return handling_report(request)

    first, second = world_observation(revision=1), world_observation(revision=2)
    stage, agent, _ = await create_stage(StaleAgent())
    assert await stage.fact_sink.submit(first)
    await emitted.wait()
    assert await stage.fact_sink.submit(second)
    release.set()
    await stage.wait_idle()
    assert agent.executions == []
    await stage.close()


@pytest.mark.asyncio
async def test_one_long_lived_worker_executes_plans_serially():
    agent = RecordingAgent()
    agent.realize_gate = asyncio.Event()

    async def handle(request, sink, *, context=None):
        value = action_plan(request)
        await sink.emit(value)
        return handling_report(request, plans=(value.plan_id,))

    agent.handle_stimulus = handle
    stage, _, _ = await create_stage(agent)
    worker = stage.execution_worker
    assert await stage.fact_sink.submit(world_observation(revision=1))
    await asyncio.sleep(0)
    assert await stage.fact_sink.submit(world_observation(revision=2))

    while len(agent.executions) < 1:
        await asyncio.sleep(0)
    assert stage.execution_worker is worker and len(agent.executions) == 1
    agent.realize_gate.set()
    await stage.wait_idle()
    assert len(agent.executions) == 2 and agent.max_active_realizations == 1
    assert stage.execution_worker is worker
    await stage.close()


@pytest.mark.asyncio
async def test_no_channel_sink_refuses_output_and_close_cancels_inflight_handle():
    sink = NoChannelOutputSink()
    with pytest.raises(d.SinkRejectedError) as error:
        await sink.emit(d.TextFinalOutput(
            interaction_id="interaction", execution_id="execution", action_id="action",
            sequence_no=0, delivery=d.OutputDelivery.CONVERSATION, text="不可投递",
        ))
    assert error.value.code is d.SinkRejectionCode.SINK_CLOSED

    agent = RecordingAgent()
    agent.handle_gate = asyncio.Event()
    stage, _, factory = await create_stage(agent)
    assert await stage.fact_sink.submit(world_observation())
    request = await asyncio.wait_for(agent.requests.get(), 1)
    await stage.close()

    assert request.cancellation.reason is d.CancellationReason.NO_LONGER_NEEDED
    assert stage.state is StageState.TERMINATED and factory.created[0].closed
    assert not await stage.fact_sink.submit(world_observation())


@pytest.mark.asyncio
async def test_world_activity_handler_consumes_only_domain_fact_reference():
    from src.agent import Agent
    from src.agent.handlers.stimulus.router import StimulusRouter
    from src.agent.handlers.stimulus.world_activity import WorldActivityHandler

    stage = None

    class Handler(WorldActivityHandler):
        async def handle(self, request, plans):
            assert isinstance(request.interaction, d.WorldInteractionSnapshot)
            assert plans.context is stage._context
            assert not hasattr(request.interaction, "event_store")
            return await super().handle(request, plans)

    agent = Agent(character_id="luotianyi", stimulus_router=StimulusRouter((
        (d.StimulusKind.WORLD_OBSERVATION, Handler()),
        (d.StimulusKind.ACTIVITY_OBSERVATION, Handler()),
    )))
    stage, _, _ = await create_stage(agent)

    assert await stage.fact_sink.submit(world_observation())
    await stage.wait_idle()
    assert stage.pending_stimuli == ()
    await stage.close()
