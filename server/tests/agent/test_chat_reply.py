"""到期批次回复：生成、落库与 Say/Sing 计划交付。"""
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from routing_support import Sink, request

import src.domain.agent as d
from src.agent import Agent
from src.agent.context import ConversationEntry, SongContent, TextContent
from src.agent.handlers.stimulus.chat import ChatReplyHandler
from src.agent.handlers.stimulus.router import StimulusRouter
from src.agent.main_chat import OneSentenceChat, SongSegmentChat
from src.agent.skills.cognitive import ReplyDraft, ResponseCompositionSkill


class _Conversation:
    def __init__(self):
        self.entries = []

    async def append(self, entries):
        self.entries.extend(entries)

    def read(self):
        return SimpleNamespace(summary=SimpleNamespace(text=""), entries=tuple(self.entries))


def context(interaction_id="i", user_id="u", character_id="luotianyi"):
    value = SimpleNamespace(identity=SimpleNamespace(
        interaction_id=interaction_id, user_id=user_id, character_id=character_id))
    value.conversation = _Conversation()
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
    def __init__(self, drafts):
        self.drafts = drafts
        self.calls = []

    async def compose(self, **kwargs):
        self.calls.append(kwargs)
        return self.drafts


def agent(composer, understanding=None):
    return Agent(character_id="luotianyi", stimulus_router=StimulusRouter([
        (d.StimulusKind.TEXT_MESSAGE, ChatReplyHandler(composer, understanding or _Understanding()))]))


@pytest.mark.asyncio
async def test_batch_reply_emits_ordered_actions_persists_and_consumes():
    composer = Composer((
        ReplyDraft(content="你好呀", sound_content="你好呀", tone="happy", expression="开心"),
        ReplyDraft(content="唱了《歌》", sound_content="", tone="", expression=None, sing=("歌", "副歌")),
    ))
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
    assert composer.calls[0]["user_id"] == "u"


@pytest.mark.asyncio
async def test_empty_batch_consumes_without_plan_or_persistence():
    composer = Composer(())
    ctx = context()
    sink = Sink()
    report = await agent(composer).handle_stimulus(
        replace(request(), prepared_inputs=()), sink, context=ctx)
    assert sink.values == []
    assert ctx.conversation.entries == []
    assert report.consumed_pending_stimulus_ids == ("m2", "m1")
    assert composer.calls == []


class _Memory:
    def render_for_prompt(self):
        return ["记忆1"]


class _Mind:
    def __init__(self):
        self.memory_queries = []
        self.sing_attempts = []

    async def search_memory_context_for_topic(self, user_id, queries):
        self.memory_queries.append((user_id, tuple(queries)))
        return _Memory()

    async def build_sing_plan_for_topic(self, attempts, excluded_segments=None, emotion_context=""):
        self.sing_attempts.append(tuple(attempts))
        return ("歌", "副歌")


class _Conscious:
    def __init__(self):
        self.kwargs = None

    async def generate_topic_reply_for_pipeline(self, **kwargs):
        self.kwargs = kwargs
        return [OneSentenceChat(content="你好", tone="happy", expression="开心"),
                SongSegmentChat(song="歌", segment="副歌")]


class _Singing:
    def __init__(self):
        self.calls = []

    def get_segment_lyrics(self, character_id, song, segment):
        self.calls.append((character_id, song, segment))
        return "歌词一行"


class _Capabilities:
    def __init__(self):
        self.singing = _Singing()


class _Runtime:
    def __init__(self):
        self.mind = _Mind()
        self.conscious = _Conscious()
        self.capability_manager = _Capabilities()


@pytest.mark.asyncio
async def test_response_composition_skill_recalls_and_maps_drafts():
    runtime = _Runtime()
    skill = ResponseCompositionSkill({}, lambda character_id: runtime)
    drafts = await skill.compose(character_id="luotianyi", user_id="u", reply_topic="你好",
                                 conversation_history="历史", memory_queries=("你好",),
                                 sing_attempts=("《歌》",))
    assert [draft.sing for draft in drafts] == [None, ("歌", "副歌")]
    assert drafts[0].content == "你好"
    assert drafts[0].tone == "happy"
    assert drafts[0].expression == "开心"
    assert drafts[0].sound_content
    assert runtime.mind.memory_queries == [("u", ("你好",))]
    assert runtime.mind.sing_attempts == [("《歌》",)]
    assert runtime.conscious.kwargs["memory_hits"] == ["记忆1"]
    assert runtime.conscious.kwargs["sing_plan"] == ("歌", "副歌")
    assert runtime.conscious.kwargs["conversation_history"] == "历史"
    assert drafts[1].lyrics == "歌词一行"
    assert runtime.capability_manager.singing.calls == [("luotianyi", "歌", "副歌")]


@pytest.mark.asyncio
async def test_reply_passes_sing_attempts_and_recent_exclusion():
    composer = Composer(())
    ctx = context()
    ctx.conversation.entries.append(ConversationEntry(
        entry_id="p1",
        timestamp=datetime.now(timezone.utc).astimezone().replace(tzinfo=None),
        source="agent",
        content=SongContent("唱了《歌》", "歌", "副歌")))
    await agent(composer, _Understanding(("《歌》",))).handle_stimulus(
        deadline_request(), Sink(), context=ctx)
    assert composer.calls[0]["sing_attempts"] == ("《歌》",)
    assert composer.calls[0]["excluded_segments"] == {("歌", "副歌")}
