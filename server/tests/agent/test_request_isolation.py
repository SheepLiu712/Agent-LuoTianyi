"""不同请求和角色的单次处理互相隔离。"""
from dataclasses import replace
from datetime import timedelta

import pytest

import src.domain.agent as d
from routing_support import Sink, plan_and_context, request, settlement
from plan_emission_support import draft


async def deliver(req, plans):
    plan, _ = plan_and_context()
    plan = replace(plan, origin_request_id=req.request_id,
                   target_character_id=req.stimulus.target_character_ids[0],
                   interaction_id=req.interaction.interaction_id,
                   basis_interaction_revision=req.interaction.interaction_revision)
    receipt = await plans.emit(draft(actions=plan.actions, sources=plan.source_stimulus_ids))
    return settlement(req, emitted=(receipt.plan_id,), reconsider_at=req.interaction.now + timedelta(seconds=7))


@pytest.mark.asyncio
async def test_request_and_character_keys_remain_independent(routed_runtime):
    runtime, _ = routed_runtime(handle=deliver)
    await runtime.get_agent().handle_stimulus(request(), Sink())
    sink = Sink()
    assert (await runtime.get_agent().handle_stimulus(replace(request(), request_id="r2"), sink)).emitted_plan_ids == (sink.values[0].plan_id,)
    req = request()
    items = tuple(replace(item, target_character_ids=("miku",)) for item in req.interaction.pending_stimuli)
    req = replace(req, stimulus=items[0], interaction=replace(req.interaction, pending_stimuli=items))
    assert (await runtime.get_agent("miku").handle_stimulus(req, sink)).request_status is d.HandlingRequestStatus.COMPLETED
    assert len(sink.values) == 2
