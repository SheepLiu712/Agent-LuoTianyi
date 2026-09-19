"""到期批次回复：生成、落库与 Say/Sing 计划交付。"""

from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from routing_support import Sink, request

import src.domain.agent as d
from src.agent import Agent
from src.agent.context import ConversationEntry, SongContent, TextContent, UserContextSnapshot
from src.agent.handlers.stimulus.chat import ChatReplyHandler
from src.agent.handlers.stimulus.router import StimulusRouter
from src.agent.skills.cognitive import (
    ComposedReply,
    ComposedResponse,
    ReplyDraft,
    ResponseCompositionSkill,
)
from skill_support import invocation


class _Conversation:
    def __init__(self):
        self.entries = []

    async def append(self, entries):
        self.entries.extend(entries)

    def read(self):
        return SimpleNamespace(summary=SimpleNamespace(text=""), entries=tuple(self.entries))


def context(interaction_id="i", user_id="u", character_id="luotianyi"):
    value = SimpleNamespace(
        identity=SimpleNamespace(interaction_id=interaction_id, user_id=user_id, character_id=character_id)
    )
    value.conversation = _Conversation()
    value.user = SimpleNamespace(read=UserContextSnapshot)
    return value


def deadline_request():
    prepared = d.PreprocessedInput(stimulus_id="m2", text="你好", conversation_entry_ids=("e1",))
    return replace(request(), prepared_inputs=(prepared,))


class _Understanding:
    def __init__(self, terms=()):
        self.terms = tuple(terms)

    def extract_terms(self, text):
        return self.terms


class Composer:
    def __init__(self, drafts, provisional=None):
        self.drafts = drafts
        self.provisional = provisional
        self.calls = []

    async def compose(self, skill_invocation, **kwargs):
        kwargs["invocation"] = skill_invocation
        self.calls.append(kwargs)
        return self.drafts

    async def compose_staged(self, skill_invocation, **kwargs):
        kwargs["invocation"] = skill_invocation
        self.calls.append(kwargs)

        async def formal():
            return ComposedReply(drafts=self.drafts)

        return ComposedResponse(provisional=self.provisional, pending=formal)


def agent(composer, understanding=None):
    return Agent(
        character_id="luotianyi",
        stimulus_router=StimulusRouter(
            [(d.StimulusKind.TEXT_MESSAGE, ChatReplyHandler(composer, understanding or _Understanding()))]
        ),
    )


@pytest.mark.asyncio
async def test_batch_reply_emits_ordered_actions_persists_and_consumes():
    composer = Composer(
        (
            ReplyDraft(content="你好呀", sound_content="你好呀", tone="happy", expression="开心"),
            ReplyDraft(content="唱了《歌》", sound_content="", tone="", expression=None, sing=("歌", "副歌")),
        )
    )
    ctx = context()
    sink = Sink()
    report = await agent(composer).handle_stimulus(deadline_request(), sink, context=ctx)
    thinking, plan = sink.values
    assert [action.kind for action in thinking.actions] == [d.ActionKind.START_THINKING]
    assert thinking.plan_ordinal == 0
    assert isinstance(plan, d.ActionPlan)
    assert plan.plan_ordinal == 1
    kinds = [action.kind for action in plan.actions]
    assert kinds == [d.ActionKind.SAY, d.ActionKind.SING]
    assert plan.actions[0].content == "你好呀"
    assert plan.actions[0].tone.value == "happy"
    assert plan.actions[0].expression.expression_id == "开心"
    assert plan.actions[1].song_id == "歌" and plan.actions[1].segment_id == "副歌"
    assert plan.source_stimulus_ids == ("m2", "m1")
    assert [entry.source for entry in ctx.conversation.entries] == ["agent", "agent"]
    assert isinstance(ctx.conversation.entries[0].content, TextContent)
    assert ctx.conversation.entries[0].content.text == "你好呀"
    assert isinstance(ctx.conversation.entries[1].content, SongContent)
    assert ctx.conversation.entries[1].content.song == "歌"
    assert report.consumed_pending_stimulus_ids == ("m2", "m1")
    assert report.retained_pending_stimulus_ids == ()
    assert composer.calls[0]["reply_topic"] == "你好"
    assert composer.calls[0]["invocation"].user_id == "u"


@pytest.mark.asyncio
async def test_empty_batch_consumes_without_plan_or_persistence():
    composer = Composer(())
    ctx = context()
    sink = Sink()
    report = await agent(composer).handle_stimulus(replace(request(), prepared_inputs=()), sink, context=ctx)
    assert sink.values == []
    assert ctx.conversation.entries == []
    assert report.consumed_pending_stimulus_ids == ("m2", "m1")
    assert composer.calls == []


class _Recall:
    def render_for_prompt(self):
        return ["记忆1"]

    hits = ()


class _Memory:
    def __init__(self):
        self.memory_queries = []

    async def search_memory_context_for_topic(self, user_id, queries):
        self.memory_queries.append((user_id, tuple(queries)))
        return _Recall()


class _Generator:
    def __init__(self):
        self.kwargs = None

    async def generate(self, **kwargs):
        self.kwargs = kwargs
        return (
            ReplyDraft(content="你好", sound_content="你好", tone="happy", expression="开心"),
            ReplyDraft(content="唱了《歌》", sound_content="", tone="", expression=None, sing=("歌", "副歌")),
        )


class _Singing:
    def __init__(self):
        self.calls = []
        self.plan_calls = []

    async def build_sing_plan(self, character_id, attempts, *, excluded_segments=None, emotion_context=""):
        self.plan_calls.append((character_id, tuple(attempts), excluded_segments))
        return ("歌", "副歌")

    def get_segment_lyrics(self, character_id, song, segment):
        self.calls.append((character_id, song, segment))
        return "歌词一行"


@pytest.mark.asyncio
async def test_response_composition_skill_recalls_and_maps_drafts():
    memory = _Memory()
    singing = _Singing()
    generator = _Generator()
    skill = ResponseCompositionSkill(
        {}, memories={"luotianyi": memory}, singing=singing, generators={"luotianyi": generator}
    )
    drafts = await skill.compose(
        invocation(),
        user_context=UserContextSnapshot(),
        reply_topic="你好",
        conversation_history="历史",
        memory_queries=("你好",),
        sing_attempts=("《歌》",),
    )
    assert [draft.sing for draft in drafts] == [None, ("歌", "副歌")]
    assert drafts[0].content == "你好"
    assert drafts[0].tone == "happy"
    assert drafts[0].expression == "开心"
    assert drafts[0].sound_content
    assert memory.memory_queries == [("u", ("你好",))]
    assert singing.plan_calls == [("luotianyi", ("《歌》",), None)]
    assert generator.kwargs["memory_hits"] == ["记忆1"]
    assert generator.kwargs["sing_plan"] == ("歌", "副歌")
    assert generator.kwargs["conversation_history"] == "历史"
    assert drafts[1].lyrics == "歌词一行"
    assert singing.calls == [("luotianyi", "歌", "副歌")]


@pytest.mark.asyncio
async def test_reply_passes_sing_attempts_and_recent_exclusion():
    composer = Composer(())
    ctx = context()
    ctx.conversation.entries.append(
        ConversationEntry(
            entry_id="p1",
            timestamp=datetime.now(timezone.utc).astimezone().replace(tzinfo=None),
            source="agent",
            content=SongContent("唱了《歌》", "歌", "副歌"),
        )
    )
    await agent(composer, _Understanding(("《歌》",))).handle_stimulus(deadline_request(), Sink(), context=ctx)
    assert composer.calls[0]["sing_attempts"] == ("《歌》",)
    assert composer.calls[0]["excluded_segments"] == {("歌", "副歌")}
