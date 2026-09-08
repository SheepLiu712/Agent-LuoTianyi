"""Agent 交互中断状态的阶段变化、隔离及结束清理。"""
import asyncio
from dataclasses import replace

import pytest
import src.domain.agent as d
from routing_support import Sink, request, plan_and_context, settlement, completed


@pytest.mark.asyncio
async def test_handle_and_realize_states_are_independent_and_released(routed_runtime):
    handles, executions = asyncio.Queue(), asyncio.Queue()
    finish = asyncio.Event()
    async def handle(req, plans):
        plans.set_interruptible(True)
        handles.put_nowait(plans)
        await finish.wait()
        return settlement(req)
    async def realize(action, context, outputs):
        outputs.set_interruptible(True)
        executions.put_nowait(outputs)
        await finish.wait()
        return completed(action)
    runtime, _ = routed_runtime(handle=handle, realize=realize)
    agent = runtime.get_agent()
    assert not agent.is_handle_interruptible("i") and not agent.is_realize_interruptible("i")
    handling = asyncio.create_task(agent.handle_stimulus(request(), Sink()))
    plans = await asyncio.wait_for(handles.get(), 1)
    assert agent.is_handle_interruptible("i") and not agent.is_handle_interruptible("other")
    value, context = plan_and_context()
    value = replace(value, actions=value.actions[:1])
    realizing = asyncio.create_task(agent.realize_action_plan(value, context, Sink()))
    outputs = await asyncio.wait_for(executions.get(), 1)
    assert agent.is_realize_interruptible("i")
    plans.set_interruptible(False)
    assert not agent.is_handle_interruptible("i") and agent.is_realize_interruptible("i")
    finish.set()
    await asyncio.gather(handling, realizing)
    assert not agent.is_handle_interruptible("i") and not agent.is_realize_interruptible("i")
    for emitter in (plans, outputs):
        with pytest.raises(RuntimeError):
            emitter.set_interruptible(True)


@pytest.mark.asyncio
async def test_cancelled_extraction_finishes_call_but_retains_all_inputs(routed_runtime):
    entered, finish = asyncio.Event(), asyncio.Event()
    async def handle(req, plans):
        plans.set_interruptible(True)
        entered.set()
        await finish.wait()
        return settlement(req)
    runtime, _ = routed_runtime(handle=handle)
    agent, req = runtime.get_agent(), request()
    task = asyncio.create_task(agent.handle_stimulus(req, Sink()))
    await entered.wait()
    req.cancellation.cancel(d.CancellationReason.SUPERSEDED)
    assert not task.done()
    finish.set()
    result = await task
    assert result.request_status is d.HandlingRequestStatus.CANCELLED
    assert not result.consumed_pending_stimulus_ids
    assert result.retained_pending_stimulus_ids == ("m2", "m1")
    assert not agent.is_handle_interruptible("i")


@pytest.mark.asyncio
async def test_cannot_enter_reply_phase_after_extraction_was_invalidated(routed_runtime):
    entered, finish = asyncio.Event(), asyncio.Event()
    replied = []
    async def handle(req, plans):
        plans.set_interruptible(True)
        entered.set()
        await finish.wait()
        plans.set_interruptible(False)
        replied.append(True)
        return settlement(req)
    runtime, _ = routed_runtime(handle=handle)
    req = request()
    task = asyncio.create_task(runtime.get_agent().handle_stimulus(req, Sink()))
    await entered.wait()
    req.cancellation.cancel(d.CancellationReason.SUPERSEDED)
    finish.set()
    assert (await task).request_status is d.HandlingRequestStatus.CANCELLED
    assert not replied


@pytest.mark.asyncio
async def test_later_revision_does_not_reject_accepted_plan(routed_runtime):
    async def realize(action, context, outputs):
        return completed(action)
    runtime, _ = routed_runtime(realize=realize)
    value, context = plan_and_context()
    result = await runtime.get_agent().realize_action_plan(
        value, replace(context, current_interaction_revision=context.current_interaction_revision + 2), Sink())
    assert result.status is d.ExecutionStatus.COMPLETED


@pytest.mark.asyncio
async def test_task_cancellation_cleans_only_its_interaction(routed_runtime):
    entered = asyncio.Queue()
    async def handle(req, plans):
        plans.set_interruptible(True)
        entered.put_nowait(req.interaction.interaction_id)
        await asyncio.Event().wait()
    runtime, _ = routed_runtime(handle=handle)
    agent, req = runtime.get_agent(), request()
    other = replace(req, request_id="other", interaction=replace(req.interaction, interaction_id="other"))
    tasks = [asyncio.create_task(agent.handle_stimulus(value, Sink())) for value in (req, other)]
    await entered.get()
    await entered.get()
    tasks[0].cancel()
    await asyncio.gather(tasks[0], return_exceptions=True)
    assert not agent.is_handle_interruptible("i") and agent.is_handle_interruptible("other")
    tasks[1].cancel()
    await asyncio.gather(tasks[1], return_exceptions=True)
    assert not agent.is_handle_interruptible("other")
