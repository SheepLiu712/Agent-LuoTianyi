"""输入归属由 Stage 指定，Agent 不维护跨调用的准备状态。"""
from dataclasses import replace
import pytest
import src.domain.agent as d
from src.agent import Agent
from src.agent.handlers.stimulus.router import StimulusRouter
from src.agent.handlers.stimulus.chat import ChatPreprocessingHandler, ChatReplyHandler, ChatReflectionHandler
from routing_support import Sink, request


@pytest.mark.asyncio
async def test_agent_processes_explicit_inputs_without_caching_ownership():
    agent = Agent(character_id="luotianyi", stimulus_router=StimulusRouter([
        (d.StimulusKind.TEXT_MESSAGE, ChatPreprocessingHandler())], reflection_handler=ChatReflectionHandler()))
    first = await agent.handle_stimulus(request(), Sink())
    second = await agent.handle_stimulus(replace(request(), request_id="second"), Sink())
    assert first.preprocessed_input == second.preprocessed_input
    assert not hasattr(agent, "_handling_states")
    assert first.consumed_pending_stimulus_ids == ()
    assert first.preprocessed_input.conversation_entry_ids == ()
    reflected = await agent.handle_stimulus(replace(request(), purpose=d.HandlePurpose.REFLECT), Sink())
    assert reflected.request_status is d.HandlingRequestStatus.COMPLETED
    assert reflected.preprocessed_input is None
