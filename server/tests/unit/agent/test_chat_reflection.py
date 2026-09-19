"""回复结算后的反思：记忆沉淀、压缩与画像更新。"""
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace

import pytest

import src.domain.agent as d
from src.agent import Agent
from src.agent.context import ConversationEntry, ConversationSnapshot, ConversationSummary, TextContent
from src.agent.handlers.stimulus.chat import ChatReflectionHandler
from src.agent.handlers.stimulus.router import StimulusRouter
from src.agent.skills.reflection import ReflectionSkill
from routing_support import Sink, request


class _Conversation:
    def __init__(self, entries=()):
        self.entries = list(entries)
        self.compacted = []

    async def append(self, values):
        self.entries.extend(values)

    async def compact(self, value):
        self.compacted.append(value)

    def read(self):
        return ConversationSnapshot(summary=ConversationSummary(""), entries=tuple(self.entries))


def context(interaction_id="i", user_id="u", character_id="luotianyi"):
    value = SimpleNamespace(identity=SimpleNamespace(
        interaction_id=interaction_id, user_id=user_id, character_id=character_id))
    value.conversation = _Conversation()
    return value


class _Reflection:
    def __init__(self):
        self.consolidated = []
        self.profiles = []

    async def consolidate_memories(self, **kwargs):
        self.consolidated.append(kwargs)
        return {"ok": True}

    async def update_profile(self, **kwargs):
        self.profiles.append(kwargs)
        return "新画像"


class _Compaction:
    def __init__(self, result=None):
        self.result = result
        self.calls = 0

    async def compact(self, conversation_context):
        self.calls += 1
        return self.result


def reflection_request():
    prepared = d.PreprocessedInput(stimulus_id="m2", text="你好", conversation_entry_ids=("u1",))
    return replace(request(), purpose=d.HandlePurpose.REFLECT, prepared_inputs=(prepared,))


def agent(reflection, compaction):
    return Agent(character_id="luotianyi", stimulus_router=StimulusRouter(
        [], reflection_handler=ChatReflectionHandler(reflection, compaction)))


@pytest.mark.asyncio
async def test_reflection_consolidates_compacts_and_updates_profile():
    ctx = context()
    await ctx.conversation.append((ConversationEntry(
        entry_id="a1", timestamp=datetime.now(), source="agent", content=TextContent("你好呀")),))
    reflection, compaction = _Reflection(), _Compaction()
    report = await agent(reflection, compaction).handle_stimulus(
        reflection_request(), Sink(), context=ctx)
    assert reflection.consolidated[0]["current_dialogue"] == "user: 你好\nagent: 你好呀"
    assert reflection.consolidated[0]["user_id"] == "u"
    assert reflection.consolidated[0]["character_id"] == "luotianyi"
    assert compaction.calls == 1
    assert reflection.profiles[0]["summary"] == ""
    assert reflection.profiles[0]["recent_conversation"] == ["agent: 你好呀"]
    assert report.request_status is d.HandlingRequestStatus.COMPLETED
    assert report.emitted_plan_ids == ()


class _Mind:
    def __init__(self):
        self.memories = []
        self.profiles = []

    async def write_topic_memories(self, user_id, current_dialogue, related_memories=None,
                                   history=None, commit=True):
        self.memories.append((user_id, current_dialogue, history))
        return {"written": True}

    async def update_user_profile_by_context(self, user_id, context, commit=True):
        self.profiles.append((user_id, context))
        return "新"


@pytest.mark.asyncio
async def test_reflection_skill_maps_memory_and_profile_calls():
    mind = _Mind()
    skill = ReflectionSkill({}, mind)
    await skill.consolidate_memories(character_id="luotianyi", user_id="u",
                                     current_dialogue="对话", conversation_history="历史")
    result = await skill.update_profile(character_id="luotianyi", user_id="u",
                                        summary="总结", recent_conversation=["agent: 你好"])
    assert mind.memories == [("u", "对话", "历史")]
    assert mind.profiles == [("u", {"summary": "总结", "recent_conversation": ["agent: 你好"]})]
    assert result == "新"
