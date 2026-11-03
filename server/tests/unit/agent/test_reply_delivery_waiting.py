"""慢召回只在完成后交付一轮正式回复。"""

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest
from support.reply_capabilities import scripted_reply_skills
from support.routing_support import Sink, request

import src.domain.agent as d
from src.agent import Agent
from src.agent.context import UserContextSnapshot
from src.agent.context.recalled_memory_context import RecalledMemoryContext
from src.agent.handlers.stimulus.chat import ChatReplyHandler
from src.agent.handlers.stimulus.router import StimulusRouter
from src.agent.processing.reply_materials import ReplyGenerationResult
from src.agent.skills.cognitive import (
    ReplyDraft,
)
from src.domain.memory_context import MemoryHit


class _Conversation:
    def __init__(self):
        self.entries = []

    async def append(self, entries):
        self.entries.extend(entries)

    def read(self):
        return SimpleNamespace(summary=SimpleNamespace(text=""), entries=tuple(self.entries))


def context(user_id="u", character_id="luotianyi"):
    value = SimpleNamespace(identity=SimpleNamespace(interaction_id="i", user_id=user_id, character_id=character_id))
    value.conversation = _Conversation()
    value.recalled_memory = RecalledMemoryContext()
    value.user = SimpleNamespace(read=UserContextSnapshot)
    return value


def deadline_request():
    prepared = d.PreprocessedInput(stimulus_id="m2", text="你好", conversation_entry_ids=("e1",))
    return replace(request(), prepared_inputs=(prepared,))


class _Understanding:
    def recognize(self, text):
        return ()


FORMAL = ReplyDraft(content="我记得你喜欢乌龙茶", sound_content="我记得你喜欢乌龙茶", tone="happy", expression="微笑脸")
SING_ONLY = ReplyDraft(content="", sound_content="", tone="", expression=None, sing=("乌龙茶", "副歌"))


class _DraftProducer:
    """在门控事件后提供正式草稿，检验交付和取消边界。"""

    def __init__(self, *, formal=(FORMAL,), hits=(), gate=None):
        self.formal_drafts = formal
        self.hits = hits
        self.gate = gate
        self.formal_calls = 0

    async def generate_drafts(self, invocation, **kwargs):
        self.formal_calls += 1
        if self.gate is not None:
            await self.gate.wait()
        return ReplyGenerationResult(drafts=self.formal_drafts, memory_hits=self.hits)


def agent(composer):
    return Agent(
        character_id="luotianyi",
        stimulus_router=StimulusRouter(
            [(d.StimulusKind.TEXT_MESSAGE, ChatReplyHandler(scripted_reply_skills(composer)))]
        ),
    )


@pytest.mark.asyncio
async def test_only_formal_reply_is_delivered_after_waiting():
    sink = Sink()
    composer = _DraftProducer()
    report = await agent(composer).handle_stimulus(deadline_request(), sink, context=context())

    thinking, formal, reflection = sink.values
    assert [plan.plan_ordinal for plan in sink.values] == [0, 1, 2]
    assert [action.kind for action in thinking.actions] == [d.ActionKind.START_THINKING]
    assert [action.kind for action in formal.actions] == [d.ActionKind.SAY]
    assert formal.actions[0].content == "我记得你喜欢乌龙茶"
    assert isinstance(reflection.actions[0], d.CognitiveMaintenance)
    assert formal.source_stimulus_ids == ("m2", "m1")
    assert composer.formal_calls == 1
    assert report.request_status is d.HandlingRequestStatus.COMPLETED
    assert report.emitted_plan_ids == tuple(plan.plan_id for plan in sink.values)


@pytest.mark.asyncio
async def test_all_emitted_plans_carry_the_same_basis_interaction_revision():
    sink = Sink()
    value = deadline_request()

    await agent(_DraftProducer()).handle_stimulus(value, sink, context=context())

    basis = {plan.basis_interaction_revision for plan in sink.values}
    assert basis == {value.interaction.interaction_revision}


@pytest.mark.asyncio
async def test_recalled_memory_is_attached_to_the_triggering_stimulus():
    hits = (MemoryHit(rendered_text="喜欢乌龙茶", score=0.9, query="你好"),)
    ctx = context()

    await agent(_DraftProducer(hits=hits)).handle_stimulus(deadline_request(), Sink(), context=ctx)

    entries = ctx.recalled_memory.read()
    assert [entry.stimulus_id for entry in entries] == ["m2"]
    assert [entry.content.rendered_text for entry in entries] == ["喜欢乌龙茶"]


@pytest.mark.asyncio
async def test_cancellation_blocks_the_formal_plan_and_its_late_output():
    gate = asyncio.Event()
    composer = _DraftProducer(gate=gate)
    sink = Sink()
    value = deadline_request()
    ctx = context()

    task = asyncio.create_task(agent(composer).handle_stimulus(value, sink, context=ctx))
    while composer.formal_calls < 1:
        await asyncio.sleep(0)
    value.cancellation.cancel(d.CancellationReason.SUPERSEDED)
    # 召回在取消之后才返回：迟到结果必须被丢弃。
    gate.set()
    report = await task

    assert [plan.plan_ordinal for plan in sink.values] == [0]
    assert all(
        action.content != "我记得你喜欢乌龙茶"
        for plan in sink.values
        for action in plan.actions
        if isinstance(action, d.Say)
    )
    assert composer.formal_calls == 1
    assert report.request_status is d.HandlingRequestStatus.CANCELLED
    assert report.emitted_plan_ids == tuple(plan.plan_id for plan in sink.values)
    assert report.retryable is False
    assert ctx.recalled_memory.read() == ()


@pytest.mark.asyncio
async def test_handle_becomes_non_interruptible_when_first_say_is_ready():
    compose_entered = asyncio.Event()
    compose_gate = asyncio.Event()
    formal_gate = asyncio.Event()

    class ControlledComposer(_DraftProducer):
        async def generate_drafts(self, invocation, **kwargs):
            compose_entered.set()
            await compose_gate.wait()
            return await super().generate_drafts(invocation, **kwargs)

    composer = ControlledComposer(gate=formal_gate)
    facade = agent(composer)
    sink = Sink()
    value = deadline_request()
    task = asyncio.create_task(facade.handle_stimulus(value, sink, context=context()))

    await compose_entered.wait()
    assert facade.is_handle_interruptible("i", value.request_id)

    compose_gate.set()
    while composer.formal_calls < 1:
        await asyncio.sleep(0)
    assert len(sink.values) == 1
    assert facade.is_handle_interruptible("i", value.request_id)

    formal_gate.set()
    while len(sink.values) < 2:
        await asyncio.sleep(0)
    assert isinstance(sink.values[1].actions[0], d.Say)
    assert not facade.is_handle_interruptible("i", value.request_id)

    await task


@pytest.mark.asyncio
async def test_handle_becomes_non_interruptible_when_first_sing_is_ready():
    formal_gate = asyncio.Event()
    sing_emitted = asyncio.Event()
    sink_release = asyncio.Event()

    async def receive(plan):
        sink.values.append(plan)
        if any(isinstance(action, d.Sing) for action in plan.actions):
            sing_emitted.set()
            await sink_release.wait()
        return d.PlanReceipt(plan_id=plan.plan_id, status=d.PlanAcceptanceStatus.ACCEPTED)

    composer = _DraftProducer(formal=(SING_ONLY,), gate=formal_gate)
    facade = agent(composer)
    sink = Sink(receive)
    value = deadline_request()
    task = asyncio.create_task(facade.handle_stimulus(value, sink, context=context()))

    formal_gate.set()
    await sing_emitted.wait()
    assert not facade.is_handle_interruptible("i", value.request_id)

    sink_release.set()
    await task


@pytest.mark.asyncio
async def test_sink_failure_on_formal_plan_stops_without_retry():
    delivered = []

    async def reject(plan):
        delivered.append(plan)
        if plan.plan_ordinal == 1:
            raise d.SinkRejectedError("closed", code=d.SinkRejectionCode.SINK_CLOSED)
        return d.PlanReceipt(plan_id=plan.plan_id, status=d.PlanAcceptanceStatus.ACCEPTED)

    composer = _DraftProducer()
    report = await agent(composer).handle_stimulus(deadline_request(), Sink(reject), context=context())

    assert [plan.plan_ordinal for plan in delivered] == [0, 1]
    assert composer.formal_calls == 1
    assert report.request_status is d.HandlingRequestStatus.FAILED
    assert report.error_code is d.HandlingErrorCode.SINK_CLOSED
    assert report.retryable is False


@pytest.mark.asyncio
async def test_waiting_reply_never_reenters_the_public_stimulus_interface():
    sink = Sink()
    handled = []

    class _Observed(ChatReplyHandler):
        async def handle(self, value, plans):
            handled.append(value.stimulus.stimulus_id)
            return await super().handle(value, plans)

    handler = _Observed(scripted_reply_skills(_DraftProducer()))
    facade = Agent(character_id="luotianyi", stimulus_router=StimulusRouter([(d.StimulusKind.TEXT_MESSAGE, handler)]))

    await facade.handle_stimulus(deadline_request(), sink, context=context())

    # 召回结果留在本次 handle 内：既没有新增刺激种类，也没有第二次进入处理器。
    assert handled == ["m2"]
    assert not hasattr(d, "RecallCompleted")
    assert all(name != "RECALL_COMPLETED" for name in d.StimulusKind.__members__)
    assert all(isinstance(plan, d.ActionPlan) for plan in sink.values)


@pytest.mark.asyncio
async def test_cancelled_retrieval_closes_before_reply_generation_or_delivery():
    entered, closed = asyncio.Event(), asyncio.Event()
    skills = scripted_reply_skills(_DraftProducer())

    async def blocked_search(invocation, *, query):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()

    skills.retrieval.search = blocked_search
    handler = ChatReplyHandler(skills)
    facade = Agent(character_id="luotianyi", stimulus_router=StimulusRouter([(d.StimulusKind.TEXT_MESSAGE, handler)]))
    sink, ctx = Sink(), context()
    task = asyncio.create_task(facade.handle_stimulus(deadline_request(), sink, context=ctx))
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()
    assert ctx.conversation.entries == []
    assert all(isinstance(action, d.StartThinking) for plan in sink.values for action in plan.actions)
