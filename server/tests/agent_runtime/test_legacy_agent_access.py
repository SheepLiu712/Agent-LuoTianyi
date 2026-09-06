"""冻结旧链路在 get_agent 返回新门面后的取对象行为。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.agent_runtime import agent_runtime as runtime_module
from src.agent.main_chat import OneSentenceChat
from src.chat_session.chat_pipeline import topic_replier as replier_module
from src.domain.chat import ExtractedTopic
from src.system.system_runtime import SystemRuntime


class TwoMethodAgent:
    async def handle_stimulus(self, request, plan_sink):
        pytest.fail("旧聊天不应进入新 handle")

    async def realize_action_plan(self, plan, execution_context, output_sink):
        pytest.fail("旧聊天不应进入新 realize")


class SplitRuntime:
    """在公开运行时边界模拟已迁移的 get_agent，旧访问仍提供原对象。"""
    def __init__(self):
        self.facade = TwoMethodAgent()
        self.legacy = {key: object() for key in ("luotianyi", "miku")}
        self.facade_lookups = []
        self.legacy_lookups = []
        self.plan_topic_turn = AsyncMock(return_value="old-plan")
        self.realize_topic_plan = AsyncMock(return_value=[OneSentenceChat(content="旧链回复")])

    def get_agent(self, character_id=None):
        self.facade_lookups.append(character_id)
        if character_id == "missing":
            raise KeyError(character_id)
        return self.facade

    def get_character_runtime(self, character_id=None):
        self.legacy_lookups.append(character_id)
        return SimpleNamespace(conscious=self.legacy[character_id or "luotianyi"])


def system_for(runtime):
    return SystemRuntime(
        user_interface=None, world=None, database_manager=None, agent_runtime=runtime,
        capability_manager=None, chat_session_manager=None, llm_service=None,
        client_llm_executor=None, observability=None,
    )


def test_system_agent_property_keeps_legacy_identity_after_get_agent_changes():
    runtime = SplitRuntime()
    system = system_for(runtime)
    assert system.agent is runtime.legacy["luotianyi"]
    assert runtime.facade_lookups == []
    assert runtime.legacy_lookups == [None]


def test_global_default_agent_keeps_legacy_identity_after_get_agent_changes(monkeypatch):
    runtime = SplitRuntime()
    monkeypatch.setattr(runtime_module, "_agent_runtime", runtime)
    assert runtime_module.get_default_agent() is runtime.legacy["luotianyi"]
    assert runtime.facade_lookups == []
    assert runtime.legacy_lookups == [None]


@pytest.mark.parametrize("character_id", ["luotianyi", "miku", "missing"])
async def test_topic_queue_uses_legacy_lookup_and_still_delivers_reply(monkeypatch, character_id):
    runtime = SplitRuntime()
    system = system_for(runtime)
    speaking = SimpleNamespace(enqueue=AsyncMock())
    conversations = SimpleNamespace(persist_agent_replies=AsyncMock(return_value=["reply-id"]))
    system.chat_session_manager = SimpleNamespace(
        global_speaking_worker=speaking, conversation_service=conversations,
    )
    monkeypatch.setattr(replier_module, "get_observability_service", lambda: None)
    completed = []

    async def reflect(turn):
        completed.append(turn)

    async def context(**kwargs):
        return {} if kwargs.get("ret_type") == "dict" else "历史对话"

    replier = replier_module.TopicReplier(
        {}, "用户", "u", character_id=character_id, context_provider=context,
        reflection_submitter=reflect,
    )
    replier.set_system_runtime(system)
    replier.set_send_reply_callback(AsyncMock())
    replier.set_change_state_callback(AsyncMock())
    replier.start_processing()
    try:
        await replier.add_topic(ExtractedTopic(
            topic_id="topic", source_messages=[], topic_content="你好",
            memory_attempts=[], fact_constraints=[], sing_attempts=[],
            target_character_ids=(character_id,),
        ))
        await asyncio.wait_for(replier.topic_queue.join(), timeout=1)
        assert len(completed) == 1, "旧流程应完成持久化、发送和反思交付"
        job = speaking.enqueue.call_args.args[0]
        assert job.job_content.content == "旧链回复"
        assert job.job_content.uuid == "reply-id"
        assert completed[0].conversation_history == "历史对话"
        runtime.plan_topic_turn.assert_awaited_once()
        runtime.realize_topic_plan.assert_awaited_once()
        assert runtime.facade_lookups == [], "旧 TopicReplier 必须改走 get_character_runtime"
        expected = [character_id, None] if character_id == "missing" else [character_id]
        assert runtime.legacy_lookups == expected
    finally:
        replier.processor_task.cancel()
        await asyncio.gather(replier.processor_task, return_exceptions=True)
