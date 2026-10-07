"""长期 WorldStage 的事实结算、计划串行与关闭行为。"""
import asyncio

import pytest
from support.world_stage_fakes import (
    RecordingAgent,
    action_plan,
    create_stage,
    handling_report,
    world_observation,
)

import src.domain.agent as d
from src.domain.stage import StageState
from src.stage import NoChannelOutputSink


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
