"""Agent 保持取消类别，只把本次取消收尾异常写入本次令牌。"""

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest
from support.routing_support import Sink, plan_and_context, request

import src.domain.agent as d
from src.agent import Agent
from src.agent.handlers.action.router import ActionRouter
from src.agent.handlers.stimulus.router import StimulusRouter


@pytest.mark.asyncio
@pytest.mark.parametrize("side", ["handle", "realize"])
@pytest.mark.parametrize("outcome", ["cancel", "cleanup_error", "business_error_before_cancel"])
async def test_agent_cancellation_cleanup_fact_is_call_local(side, outcome):
    entered, release, cleanup_release = (asyncio.Event() for _ in range(3))
    owner = None

    async def work(*args):
        entered.set()
        if outcome == "business_error_before_cancel":
            await release.wait()
            owner.cancel()
            raise OSError("business failed before cancellation joined it")
        try:
            await asyncio.Event().wait()
        finally:
            await cleanup_release.wait()
            if outcome == "cleanup_error":
                raise OSError("cancel cleanup could not close resource")

    agent = Agent(
        character_id="luotianyi",
        stimulus_router=StimulusRouter(((d.StimulusKind.TEXT_MESSAGE, SimpleNamespace(handle=work)),)),
        action_router=ActionRouter(((d.ActionKind.SAY, SimpleNamespace(realize=work)),)),
    )
    req = request()
    value, context = plan_and_context()
    value = replace(value, actions=value.actions[:1])
    token = req.cancellation if side == "handle" else context.cancellation
    operation = (
        agent.handle_stimulus(req, Sink()) if side == "handle" else agent.realize_action_plan(value, context, Sink())
    )
    owner = asyncio.create_task(operation)
    try:
        await asyncio.wait_for(entered.wait(), 1)
        if outcome == "business_error_before_cancel":
            release.set()
        else:
            token.cancel(d.CancellationReason.NO_LONGER_NEEDED)
            owner.cancel()
            cleanup_release.set()
        with pytest.raises(asyncio.CancelledError):
            await owner
        assert token.cleanup_error_type == ("OSError" if outcome == "cleanup_error" else None)
        assert d.CancellationToken().cleanup_error_type is None
    finally:
        release.set()
        cleanup_release.set()
        if not owner.done():
            owner.cancel()
        await asyncio.gather(owner, return_exceptions=True)
