"""慢召回的两段式回复：临时计划先行、正式计划随后（Issue #70）。"""
import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest
from routing_support import Sink, request

import src.domain.agent as d
from src.agent import Agent
from src.agent.context import UserContextSnapshot
from src.agent.context.recalled_memory_context import RecalledMemoryContext
from src.agent.handlers.stimulus.chat import ChatReplyHandler
from src.agent.handlers.stimulus.router import StimulusRouter
from src.agent.skills.cognitive import (
    ComposedReply,
    ComposedResponse,
    ReplyDraft,
    ResponseCompositionSkill,
)
from src.domain.memory_context import MemoryContext, MemoryHit


class _Conversation:
    def __init__(self):
        self.entries = []

    async def append(self, entries):
        self.entries.extend(entries)

    def read(self):
        return SimpleNamespace(summary=SimpleNamespace(text=""), entries=tuple(self.entries))


def context(user_id="u", character_id="luotianyi"):
    value = SimpleNamespace(identity=SimpleNamespace(
        interaction_id="i", user_id=user_id, character_id=character_id))
    value.conversation = _Conversation()
    value.recalled_memory = RecalledMemoryContext()
    value.user = SimpleNamespace(read=UserContextSnapshot)
    return value


def deadline_request():
    prepared = d.PreprocessedInput(stimulus_id="m2", text="你好", conversation_entry_ids=("e1",))
    return replace(request(), prepared_inputs=(prepared,))


class _Understanding:
    def extract_terms(self, text):
        return ()


PROVISIONAL = ReplyDraft(content="稍等我想想", sound_content="稍等我想想",
                         tone="tender", expression="温柔脸")
FORMAL = ReplyDraft(content="我记得你喜欢乌龙茶", sound_content="我记得你喜欢乌龙茶",
                    tone="happy", expression="微笑脸")


class _StagedComposer:
    """按 slice 11b 的内部两段式契约返回临时草稿与延迟的正式草稿。"""

    def __init__(self, *, provisional=(PROVISIONAL,), formal=(FORMAL,), hits=(), gate=None):
        self.provisional = provisional
        self.formal_drafts = formal
        self.hits = hits
        self.gate = gate
        self.formal_calls = 0

    async def compose(self, **kwargs):
        pytest.fail("两段式路径不得调用单段 compose")

    async def compose_staged(self, **kwargs):
        async def formal():
            self.formal_calls += 1
            if self.gate is not None:
                await self.gate.wait()
            return ComposedReply(drafts=self.formal_drafts, memory_hits=self.hits)

        return ComposedResponse(provisional=self.provisional, pending=formal)


def agent(composer):
    return Agent(character_id="luotianyi", stimulus_router=StimulusRouter([
        (d.StimulusKind.TEXT_MESSAGE, ChatReplyHandler(composer, _Understanding()))]))


@pytest.mark.asyncio
async def test_temporary_and_formal_are_two_complete_plans_with_consecutive_ordinals():
    sink = Sink()
    report = await agent(_StagedComposer()).handle_stimulus(
        deadline_request(), sink, context=context())

    thinking, temporary, formal = sink.values
    assert [plan.plan_ordinal for plan in sink.values] == [0, 1, 2]
    assert [action.kind for action in thinking.actions] == [d.ActionKind.START_THINKING]
    # 两份计划各自完整且可独立实现：都只含可直接播放的 Say。
    assert [action.kind for action in temporary.actions] == [d.ActionKind.SAY]
    assert [action.kind for action in formal.actions] == [d.ActionKind.SAY]
    assert temporary.actions[0].content == "稍等我想想"
    assert formal.actions[0].content == "我记得你喜欢乌龙茶"
    # 正式计划不修改临时计划：两者身份、行动标识彼此独立。
    assert temporary.plan_id != formal.plan_id
    assert temporary.actions[0].action_id != formal.actions[0].action_id
    assert temporary.source_stimulus_ids == formal.source_stimulus_ids == ("m2", "m1")
    assert report.request_status is d.HandlingRequestStatus.COMPLETED
    assert report.emitted_plan_ids == tuple(plan.plan_id for plan in sink.values)


@pytest.mark.asyncio
async def test_both_plans_carry_the_same_basis_interaction_revision():
    sink = Sink()
    value = deadline_request()

    await agent(_StagedComposer()).handle_stimulus(value, sink, context=context())

    basis = {plan.basis_interaction_revision for plan in sink.values}
    assert basis == {value.interaction.interaction_revision}


@pytest.mark.asyncio
async def test_recalled_memory_is_attached_to_the_triggering_stimulus():
    hits = (MemoryHit(rendered_text="喜欢乌龙茶", score=0.9, query="你好"),)
    ctx = context()

    await agent(_StagedComposer(hits=hits)).handle_stimulus(
        deadline_request(), Sink(), context=ctx)

    entries = ctx.recalled_memory.read()
    assert [entry.stimulus_id for entry in entries] == ["m2"]
    assert [entry.content.rendered_text for entry in entries] == ["喜欢乌龙茶"]


@pytest.mark.asyncio
async def test_cancellation_blocks_the_formal_plan_and_its_late_output():
    gate = asyncio.Event()
    composer = _StagedComposer(gate=gate)
    sink = Sink()
    value = deadline_request()
    ctx = context()

    task = asyncio.create_task(
        agent(composer).handle_stimulus(value, sink, context=ctx))
    while len(sink.values) < 2:
        await asyncio.sleep(0)
    value.cancellation.cancel(d.CancellationReason.SUPERSEDED)
    # 召回在取消之后才返回：迟到结果必须被丢弃。
    gate.set()
    report = await task

    assert [plan.plan_ordinal for plan in sink.values] == [0, 1]
    assert all(action.content != "我记得你喜欢乌龙茶"
               for plan in sink.values for action in plan.actions
               if isinstance(action, d.Say))
    assert composer.formal_calls == 1
    assert report.request_status is d.HandlingRequestStatus.CANCELLED
    assert report.emitted_plan_ids == tuple(plan.plan_id for plan in sink.values)
    assert report.retryable is False
    assert ctx.recalled_memory.read() == ()


@pytest.mark.asyncio
async def test_sink_failure_on_temporary_plan_stops_without_retry():
    delivered = []

    async def reject(plan):
        delivered.append(plan)
        if plan.plan_ordinal == 1:
            raise d.SinkRejectedError("closed", code=d.SinkRejectionCode.SINK_CLOSED)
        return d.PlanReceipt(plan_id=plan.plan_id, status=d.PlanAcceptanceStatus.ACCEPTED)

    composer = _StagedComposer()
    report = await agent(composer).handle_stimulus(
        deadline_request(), Sink(reject), context=context())

    assert [plan.plan_ordinal for plan in delivered] == [0, 1]
    assert composer.formal_calls == 0
    assert report.request_status is d.HandlingRequestStatus.FAILED
    assert report.error_code is d.HandlingErrorCode.SINK_CLOSED
    assert report.retryable is False


@pytest.mark.asyncio
async def test_slow_recall_never_reenters_the_public_stimulus_interface():
    sink = Sink()
    handled = []

    class _Observed(ChatReplyHandler):
        async def handle(self, value, plans):
            handled.append(value.stimulus.stimulus_id)
            return await super().handle(value, plans)

    handler = _Observed(_StagedComposer(), _Understanding())
    facade = Agent(character_id="luotianyi",
                   stimulus_router=StimulusRouter([(d.StimulusKind.TEXT_MESSAGE, handler)]))

    await facade.handle_stimulus(deadline_request(), sink, context=context())

    # 召回结果留在本次 handle 内：既没有新增刺激种类，也没有第二次进入处理器。
    assert handled == ["m2"]
    assert not hasattr(d, "RecallCompleted")
    assert all(name != "RECALL_COMPLETED" for name in d.StimulusKind.__members__)
    assert all(isinstance(plan, d.ActionPlan) for plan in sink.values)


class _Memory:
    def __init__(self, delay):
        self.delay = delay

    async def search_memory_context_for_topic(self, user_id, queries):
        if self.delay:
            await asyncio.sleep(self.delay)
        return MemoryContext(hits=(MemoryHit(rendered_text="记忆1", score=0.9, query=queries[0]),))

class _Generator:
    async def generate(self, **kwargs):
        return (ReplyDraft(content="正式回复", sound_content="正式回复", tone="happy", expression="微笑脸"),)


class _Singing:
    async def build_sing_plan(self, *args, **kwargs):
        return None

    def get_segment_lyrics(self, *args, **kwargs):
        return ""


def _composition(config, delay):
    return ResponseCompositionSkill(
        config,
        character_id="luotianyi",
        memory=_Memory(delay),
        singing=_Singing(),
        generator=_Generator(),
    )


SLOW_RECALL_CONFIG = {
    "slow_recall": {
        "provisional_after_seconds": 0.05,
        "provisional_text": "配置的临时文案",
        "provisional_sound_content": "配置的临时文案",
        "provisional_tone": "tender",
        "provisional_expression": "温柔脸",
    },
}


@pytest.mark.asyncio
async def test_skill_emits_configured_provisional_draft_only_when_recall_is_slow():
    skill = _composition(SLOW_RECALL_CONFIG, 0.5)

    staged = await skill.compose_staged(
        user_id="u", user_context=UserContextSnapshot(), reply_topic="你好",
        conversation_history="", memory_queries=("你好",))

    assert staged.provisional is not None
    assert staged.provisional[0].content == "配置的临时文案"
    assert staged.provisional[0].tone == "tender"
    assert staged.awaits_formal
    formal = await staged.formal()
    assert [draft.content for draft in formal.drafts] == ["正式回复"]
    assert [hit.rendered_text for hit in formal.memory_hits] == ["记忆1"]
    assert staged.awaits_formal is False
    assert await staged.formal() is formal


@pytest.mark.asyncio
async def test_fast_recall_and_missing_config_produce_no_provisional_draft():
    patient = {"slow_recall": dict(SLOW_RECALL_CONFIG["slow_recall"],
                                   provisional_after_seconds=30)}
    fast = await _composition(patient, 0).compose_staged(
        user_id="u", user_context=UserContextSnapshot(), reply_topic="你好",
        conversation_history="", memory_queries=("你好",))
    unconfigured = await _composition({}, 0.2).compose_staged(
        user_id="u", user_context=UserContextSnapshot(), reply_topic="你好",
        conversation_history="", memory_queries=("你好",))

    assert fast.provisional is None
    assert unconfigured.provisional is None
    assert [draft.content for draft in (await fast.formal()).drafts] == ["正式回复"]
