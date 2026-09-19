"""输入归属由 Stage 指定，Agent 不维护跨调用的准备状态。"""
from dataclasses import replace
from types import SimpleNamespace

import pytest
from routing_support import Sink, request

import src.domain.agent as d
from src.agent import Agent
from src.agent.handlers.stimulus.chat import (
    ChatPreprocessingHandler,
    ChatReflectionHandler,
)
from src.agent.handlers.stimulus.router import StimulusRouter


class _Understanding:
    def extract_terms(self, text):
        return ()


class _NoReflection:
    async def consolidate_memories(self, **kwargs):
        return {}

    async def update_profile(self, **kwargs):
        return None


class _NoCompaction:
    async def compact(self, conversation_context):
        return None


def context():
    from src.agent.context import ConversationSnapshot
    value = SimpleNamespace(identity=SimpleNamespace(
        interaction_id="i", user_id="u", character_id="luotianyi"))
    entries = []
    async def append(values):
        entries.extend(values)
    value.conversation = SimpleNamespace(
        append=append, entries=entries,
        read=lambda: ConversationSnapshot(entries=tuple(entries)))
    return value


@pytest.mark.asyncio
async def test_agent_processes_explicit_inputs_without_caching_ownership():
    agent = Agent(character_id="luotianyi", stimulus_router=StimulusRouter([
        (d.StimulusKind.TEXT_MESSAGE, ChatPreprocessingHandler(_Understanding()))],
        reflection_handler=ChatReflectionHandler(_NoReflection(), _NoCompaction())))
    first = await agent.handle_stimulus(request(), Sink(), context=context())
    second = await agent.handle_stimulus(replace(request(), request_id="second"), Sink(), context=context())
    assert first.preprocessed_input.text == second.preprocessed_input.text == "你好"
    assert first.preprocessed_input.conversation_entry_ids != second.preprocessed_input.conversation_entry_ids
    assert not hasattr(agent, "_handling_states")
    assert first.consumed_pending_stimulus_ids == ()
    reflected = await agent.handle_stimulus(replace(request(), purpose=d.HandlePurpose.REFLECT), Sink(), context=context())
    assert reflected.request_status is d.HandlingRequestStatus.COMPLETED
    assert reflected.preprocessed_input is None
