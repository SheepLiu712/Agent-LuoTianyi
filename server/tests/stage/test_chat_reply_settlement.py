"""真实聊天链路的结算与取消验收（Issue #69）。"""
import asyncio

import pytest
from test_chat_stage import cleanup, setup, stimulus

import src.domain.agent as d
from src.agent import Agent
from src.agent.handlers.action.router import ActionRouter
from src.agent.handlers.stimulus.chat import (
    ChatPreprocessingHandler,
    ChatReflectionHandler,
    ChatReplyHandler,
)
from src.agent.handlers.stimulus.interaction import InteractionEndingHandler
from src.agent.handlers.stimulus.router import StimulusRouter
from src.agent.skills.cognitive import ComposedReply, ComposedResponse, ReplyDraft


async def until(predicate):
    async def wait():
        while not predicate():
            await asyncio.sleep(0)
    await asyncio.wait_for(wait(), 2)


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


class _Composer:
    def __init__(self, drafts):
        self.drafts = drafts
        self.calls = 0

    async def compose(self, **kwargs):
        self.calls += 1
        return self.drafts

    async def compose_staged(self, **kwargs):
        self.calls += 1

        async def formal():
            return ComposedReply(drafts=self.drafts)

        return ComposedResponse(provisional=None, pending=formal)


class _Execute:
    def __init__(self, gate=None):
        self.gate = gate
        self.actions = []

    async def realize(self, action, context, outputs):
        self.actions.append(action.action_id)
        if self.gate is not None:
            await self.gate.wait()
        return d.ActionResult(action_id=action.action_id, status=d.ActionExecutionStatus.COMPLETED,
                              error_code=None, irreversible_effect_committed=False, effect_ref=None)


def build_agent(composer, execute):
    return Agent(character_id="luotianyi", stimulus_router=StimulusRouter([
        (d.StimulusKind.TEXT_MESSAGE, ChatPreprocessingHandler(_Understanding())),
        (d.StimulusKind.INTERACTION_DEADLINE, ChatReplyHandler(composer, _Understanding())),
        (d.StimulusKind.INTERACTION_ENDING, InteractionEndingHandler())],
        reflection_handler=ChatReflectionHandler(_NoReflection(), _NoCompaction())),
        action_router=ActionRouter([(d.ActionKind.SAY, execute)]))


def drafts():
    return (ReplyDraft(content="你好呀", sound_content="你好呀", tone="normal", expression=None),)


@pytest.mark.asyncio
async def test_real_batch_reply_is_realized_persisted_and_consumed():
    composer, execute = _Composer(drafts()), _Execute()
    stage, _, adapter, _, _ = await setup(build_agent(composer, execute), {"response_wait": 0.02})
    try:
        stage.stimulus_input_sink.submit(stimulus())
        await until(lambda: execute.actions)
        await until(lambda: not stage._pending)
        assert composer.calls == 1
        assert [entry.source for entry in stage.context.conversation.entries] == ["user", "agent"]
    finally:
        await cleanup(stage, adapter)


@pytest.mark.asyncio
async def test_new_content_cancels_in_flight_reply_and_settles_new_batch():
    gate = asyncio.Event()
    composer, execute = _Composer(drafts()), _Execute(gate)
    stage, _, adapter, _, _ = await setup(build_agent(composer, execute), {"response_wait": 0.02})
    try:
        stage.stimulus_input_sink.submit(stimulus())
        await until(lambda: execute.actions)
        stage.stimulus_input_sink.submit(stimulus())
        gate.set()
        await until(lambda: len(execute.actions) >= 2)
        await until(lambda: not stage._pending)
        assert composer.calls >= 2
    finally:
        gate.set()
        await cleanup(stage, adapter)
