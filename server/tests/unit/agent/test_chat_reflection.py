"""回复结算后的反思：记忆沉淀、压缩与画像更新。"""

from datetime import datetime
from types import SimpleNamespace

import pytest

import src.domain.agent as d
from src.agent.context import (
    ConversationEntry,
    ConversationSnapshot,
    ConversationSummary,
    RecalledMemoryContext,
    TextContent,
)
from src.agent.handlers.action.reflection import ReflectionActionHandler
from src.agent.skills.reflection import ReflectionSkill
from skill_support import invocation


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
    value = SimpleNamespace(
        identity=SimpleNamespace(interaction_id=interaction_id, user_id=user_id, character_id=character_id)
    )
    value.conversation = _Conversation()
    value.recalled_memory = RecalledMemoryContext()
    return value


class _Reflection:
    def __init__(self):
        self.consolidated = []
        self.profiles = []

    async def consolidate_memories(self, skill_invocation, **kwargs):
        kwargs["invocation"] = skill_invocation
        self.consolidated.append(kwargs)
        return {"ok": True}

    async def update_profile(self, skill_invocation, **kwargs):
        kwargs["invocation"] = skill_invocation
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
    return d.Reflection(action_id="reflection", prepared_inputs=(prepared,))


def execution_context(context):
    return d.ExecutionContext(
        execution_id="execution",
        interaction_id=context.identity.interaction_id,
        current_interaction_revision=3,
        cancellation=d.CancellationToken(),
        interaction_context=context,
    )


@pytest.mark.asyncio
async def test_reflection_consolidates_compacts_and_updates_profile():
    ctx = context()
    await ctx.conversation.append(
        (ConversationEntry(entry_id="a1", timestamp=datetime.now(), source="agent", content=TextContent("你好呀")),)
    )
    reflection, compaction = _Reflection(), _Compaction()
    result = await ReflectionActionHandler("luotianyi", reflection, compaction).realize(
        reflection_request(), execution_context(ctx), None
    )
    assert reflection.consolidated[0]["current_dialogue"] == "user: 你好\nagent: 你好呀"
    assert reflection.consolidated[0]["invocation"].user_id == "u"
    assert reflection.consolidated[0]["invocation"].character_id == "luotianyi"
    assert compaction.calls == 1
    assert reflection.profiles[0]["summary"] == ""
    assert reflection.profiles[0]["recent_conversation"] == ["agent: 你好呀"]
    assert result.status is d.ActionExecutionStatus.COMPLETED


class _Mind:
    def __init__(self):
        self.memories = []
        self.profiles = []

    async def write_topic_memories(self, user_id, current_dialogue, related_memories=None, history=None, commit=True):
        self.memories.append((user_id, current_dialogue, history))
        return {"written": True}

    async def update_user_profile_by_context(self, user_id, context, commit=True):
        self.profiles.append((user_id, context))
        return "新"


@pytest.mark.asyncio
async def test_reflection_skill_maps_memory_and_profile_calls():
    mind = _Mind()
    skill = ReflectionSkill({}, {"luotianyi": mind})
    await skill.consolidate_memories(invocation(), current_dialogue="对话", conversation_history="历史")
    result = await skill.update_profile(invocation(), summary="总结", recent_conversation=["agent: 你好"])
    assert mind.memories == [("u", "对话", "历史")]
    assert mind.profiles == [("u", {"summary": "总结", "recent_conversation": ["agent: 你好"]})]
    assert result == "新"
