"""共享压缩技能及旧聊天链路的迁移行为。"""

import asyncio
from types import SimpleNamespace

import pytest

from test_context import database, entry, factory
from src.agent.skills.conversation.compaction import ConversationCompactionSkill
from src.chat_session.dependency.conversation_service import ConversationService


class LLM:
    def __init__(self):
        self.registrations = []
        self.calls = []

    def register_llm_module(self, name, config):
        self.registrations.append((name, config))
        return self

    async def generate_response(self, **kwargs):
        self.calls.append(kwargs)
        return " 新总结 "


def skill(llm, keep=1):
    return ConversationCompactionSkill({"raw_conversation_context_limit": 2,
        "not_zip_conversation_count": keep, "llm_module": {"model": "test"}}, llm)


@pytest.mark.asyncio
@pytest.mark.parametrize("keep", [0, 1])
async def test_skill_generates_result_without_mutating_context(database, keep):
    llm = LLM()
    compactor = skill(llm, keep)
    context = await factory(database).get("i", user_id="u")
    await context.conversation.append((entry(1), entry(2)))
    assert await compactor.compact(context.conversation) is None
    assert llm.calls == []
    await context.conversation.append((entry(3),))
    before = context.conversation.read()
    result = await compactor.compact(context.conversation)
    assert result.covered_entry_ids == (("1", "2") if keep else ("1", "2", "3"))
    assert result.summary.text == "新总结"
    assert ("消息3" in llm.calls[0]["recent_conversation"]) is (keep == 0)
    assert context.conversation.read() == before
    assert len(llm.registrations) == 1


@pytest.mark.asyncio
async def test_legacy_entry_applies_shared_skill_and_refreshes_snapshot(database):
    llm = LLM()
    compactor = skill(llm)
    legacy = ConversationService({}, SimpleNamespace(conversation_service=database), llm)
    assert len(llm.registrations) == 1
    legacy.wire_dependencies(database=legacy.database, llm_service=llm, conversation_compaction=compactor)
    assert await legacy.compress_context_if_needed("u") is None
    context = await factory(database).get("i", user_id="u")
    await context.conversation.append((entry(1), entry(2), entry(3)))
    result = await legacy.compress_context_if_needed("u")
    assert result.summary == "新总结"
    assert [e["uuid"] for e in result.conversations] == ["3"]
    assert len(database.get_history_from_db("u", 0, 10, "luotianyi")) == 3
    assert len(llm.registrations) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["empty", "exception"])
async def test_model_failure_does_not_write(database, failure):
    class Failed(LLM):
        async def generate_response(self, **kwargs):
            if failure == "exception":
                raise RuntimeError("model failed")
            return " "
    context = await factory(database).get("i", user_id="u")
    await context.conversation.append((entry(1), entry(2), entry(3)))
    before = context.conversation.read()
    with pytest.raises((ValueError, RuntimeError)):
        await skill(Failed()).compact(context.conversation)
    assert context.conversation.read() == before


@pytest.mark.asyncio
async def test_shared_skill_keeps_concurrent_contexts_separate(database):
    class Echo(LLM):
        async def generate_response(self, **kwargs):
            await asyncio.sleep(0)
            return kwargs["recent_conversation"]
    compactor = skill(Echo())
    a = await factory(database).get("a", user_id="u")
    from src.agent.context import ContextFactory
    b = await ContextFactory(character_id="miku", database=database).get("b", user_id="u")
    await a.conversation.append((entry(1), entry(2), entry(3)))
    await b.conversation.append((entry(4), entry(5), entry(6)))
    ra, rb = await asyncio.gather(compactor.compact(a.conversation), compactor.compact(b.conversation))
    assert ra.covered_entry_ids == ("1", "2")
    assert rb.covered_entry_ids == ("4", "5")
    assert "消息4" not in ra.summary.text
    assert "消息1" not in rb.summary.text


@pytest.mark.asyncio
async def test_runtime_registers_compaction_once_for_all_characters(runtime_dependencies):
    from src.agent_runtime.agent_runtime import AgentRuntime
    kwargs, _ = runtime_dependencies
    original = kwargs["llm_service"].register_llm_module
    calls = []
    def register(name, config):
        calls.append(name)
        return original(name, config)
    kwargs["llm_service"].register_llm_module = register
    kwargs["config"]["skills"] = {"conversation_compaction": {"llm_module": {"model": "test"}}}
    runtime = AgentRuntime(**kwargs)
    try:
        assert len(runtime.character_runtimes) == 2
        assert calls.count("conversation_context_summary") == 1
        assert isinstance(runtime.skills.get(ConversationCompactionSkill), ConversationCompactionSkill)
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_append_while_skill_generates_summary_survives_application(database):
    started, proceed = asyncio.Event(), asyncio.Event()
    class Paused(LLM):
        async def generate_response(self, **kwargs):
            started.set()
            await proceed.wait()
            return "总结"
    context = await factory(database).get("i", user_id="u")
    await context.conversation.append((entry(1), entry(2), entry(3)))
    task = asyncio.create_task(skill(Paused()).compact(context.conversation))
    await asyncio.wait_for(started.wait(), 5)
    await context.conversation.append((entry(4),))
    proceed.set()
    result = await task
    await context.conversation.compact(result)
    assert [e.entry_id for e in context.conversation.read().entries] == ["3", "4"]


def test_skills_returns_same_instance_and_dispatches_config():
    from src.agent.skills import Skills
    llm = LLM()
    module_config = {"model": "specific-model"}
    skills = Skills({"conversation_compaction": {"llm_module": module_config}}, llm, tts_engine=SimpleNamespace())
    assert skills.get(ConversationCompactionSkill) is skills.get(ConversationCompactionSkill)
    assert llm.registrations == [("conversation_context_summary", module_config)]
    with pytest.raises(KeyError):
        skills.get(str)
    with pytest.raises(TypeError):
        skills.get("conversation_compaction")


@pytest.mark.parametrize("field", ["raw_conversation_context_limit", "not_zip_conversation_count", "forget_conversation_days"])
@pytest.mark.parametrize("value", [True, "60", 1.5, None, -1])
def test_compaction_validates_own_config_before_registering(field, value):
    llm = LLM()
    with pytest.raises((TypeError, ValueError), match=field):
        ConversationCompactionSkill({field: value, "llm_module": {"model": "test"}}, llm)
    assert llm.registrations == []


@pytest.mark.parametrize("config", [[], None, "config"])
def test_compaction_rejects_non_dictionary_config(config):
    with pytest.raises(TypeError, match="conversation_compaction"):
        ConversationCompactionSkill(config, LLM())


@pytest.mark.parametrize("module_config", [{}, {"custom_nested": {"provider": "value"}}, "invalid-child-config"])
def test_compaction_passes_child_config_unchanged_to_owner(module_config):
    llm = LLM()
    ConversationCompactionSkill({"llm_module": module_config, "future_submodule": {}}, llm)
    assert llm.registrations[0][1] is module_config


def test_compaction_rejects_keep_count_exceeding_threshold():
    llm = LLM()
    with pytest.raises(ValueError, match="not_zip_conversation_count"):
        ConversationCompactionSkill({"raw_conversation_context_limit": 1}, llm)
    assert llm.registrations == []


def test_compaction_propagates_child_configuration_error():
    class Rejecting(LLM):
        def register_llm_module(self, name, config):
            raise ValueError("llm_module.prompt_name is required")
    with pytest.raises(ValueError, match="llm_module.prompt_name"):
        ConversationCompactionSkill({"llm_module": {}}, Rejecting())
