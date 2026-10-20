from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

import src.domain.agent as d
from src.agent.context import (
    ContextIdentity,
    ConversationContext,
    ConversationEntry,
    ConversationSnapshot,
    ConversationSummary,
    TextContent,
)
from src.agent.context._conversation_store import EphemeralCallConversationStore
from src.agent.skills.cognitive.call_settlement import (
    CallMaintenanceSkill,
    CallSummarySkill,
    _maintenance_digest,
    render_call_turns,
)
from src.agent.skills.contracts import SkillInvocation
from src.domain.call import (
    CallEndReason,
    CallFinalSnapshot,
    CallFinalTurn,
    CallOutcome,
    CallReplyStatus,
    CallTerminalFacts,
)


def _snapshot(*, turns=(), progress=0):
    call_id = uuid4()
    return CallFinalSnapshot(
        CallTerminalFacts(call_id, CallOutcome.CONNECTED, CallEndReason.USER_HANGUP, 1000, datetime.now(timezone.utc)),
        turns,
        progress,
    )


def _invocation():
    return SkillInvocation("luotianyi", "user", "call", d.CancellationToken())


@pytest.mark.asyncio
async def test_call_summary_empty_retry_fallback_and_length_limit():
    empty = await CallSummarySkill({"luotianyi": SimpleNamespace()}).summarize(_invocation(), _snapshot())
    assert empty is None

    class Model:
        def __init__(self):
            self.calls = 0

        async def generate_response(self, **kwargs):
            self.calls += 1
            return "x" * 201 if self.calls == 1 else ""

    model = Model()
    snapshot = _snapshot(turns=(CallFinalTurn(1, "用户事实", CallReplyStatus.COMPLETED, "正式回复"),))
    assert await CallSummarySkill({"luotianyi": model}).summarize(_invocation(), snapshot) is None
    assert model.calls == 1
    assert await CallSummarySkill({}).summarize(_invocation(), snapshot) is None


@pytest.mark.asyncio
async def test_call_summary_combines_working_prefix_and_tail_updates_same_context_without_seed():
    def entry(entry_id, text):
        return ConversationEntry(entry_id, datetime(2026, 1, 1), "user", TextContent(text))

    seed = ConversationSnapshot(ConversationSummary("old seed summary"), (entry("e1", "old seed fact"),))
    conversation = ConversationContext(
        identity=ContextIdentity("luotianyi", "call", "user"),
        _store=EphemeralCallConversationStore(seed),
    )
    await conversation.append((entry("c2", "uncompressed call tail"),))
    conversation._store.update_working_summary(ConversationSummary("maintained call prefix"))
    context = SimpleNamespace(conversation=conversation)

    class Model:
        def __init__(self):
            self.inputs = []

        async def generate_response(self, **kwargs):
            self.inputs.append(kwargs)
            return "updated complete call summary"

    model = Model()
    result = await CallSummarySkill({"luotianyi": model}).summarize(
        _invocation(),
        _snapshot(turns=(CallFinalTurn(2, "uncompressed call tail", CallReplyStatus.NOT_STARTED, None),)),
        context=context,
    )

    assert result == "updated complete call summary"
    assert model.inputs == [
        {
            "completed_turns": (
                "本次通话已有摘要：maintained call prefix",
                "user：uncompressed call tail",
            )
        }
    ]
    assert "old seed" not in repr(model.inputs)
    working = conversation.read_working()
    assert working.summary.text == result
    assert tuple(item.entry_id for item in working.entries) == ("c2",)


def test_call_settlement_input_keeps_all_user_facts_and_only_completed_formal_reply():
    snapshot = _snapshot(
        turns=(
            CallFinalTurn(1, "已完整回复的用户事实", CallReplyStatus.COMPLETED, "完整角色回复"),
            CallFinalTurn(2, "尚未回复的用户事实", CallReplyStatus.NOT_STARTED, None),
            CallFinalTurn(3, "失败轮次用户事实", CallReplyStatus.FAILED, None),
            CallFinalTurn(4, "打断轮次用户事实", CallReplyStatus.INTERRUPTED, "未完整播放的partial文本"),
        )
    )

    assert render_call_turns(snapshot) == (
        "用户：已完整回复的用户事实\n角色：完整角色回复",
        "用户：尚未回复的用户事实",
        "用户：失败轮次用户事实",
        "用户：打断轮次用户事实",
    )


def test_settlement_digest_changes_with_user_or_reply_fact_and_is_stable_for_same_snapshot():
    first = _snapshot(turns=(CallFinalTurn(1, "用户事实", CallReplyStatus.NOT_STARTED, None),))
    changed_user = CallFinalSnapshot(
        first.terminal,
        (CallFinalTurn(1, "不同用户事实", CallReplyStatus.NOT_STARTED, None),),
        0,
    )
    changed_reply = CallFinalSnapshot(
        first.terminal,
        (CallFinalTurn(1, "用户事实", CallReplyStatus.COMPLETED, "正式回复"),),
        0,
    )

    assert _maintenance_digest(first) == _maintenance_digest(first)
    assert _maintenance_digest(first) != _maintenance_digest(changed_user)
    assert _maintenance_digest(first) != _maintenance_digest(changed_reply)


@pytest.mark.asyncio
async def test_call_maintenance_without_repository_has_no_cross_call_retry_cache():
    class Memory:
        def __init__(self):
            self.extracts = 0
            self.writes = 0

        async def extract_maintenance_candidates(self, **kwargs):
            self.extracts += 1
            return (d.MaintenanceCandidate(d.MaintenanceMemoryType.USER_FACT, "喜欢音乐"),)

        async def propose_user_profile(self, **kwargs):
            return "喜欢音乐的用户"

        async def write_maintenance_candidates(self, **kwargs):
            self.writes += 1
            if self.writes == 1:
                raise RuntimeError("partial write")

    memory = Memory()
    skill = CallMaintenanceSkill({"luotianyi": memory})
    snapshot = _snapshot(turns=(CallFinalTurn(1, "用户事实", CallReplyStatus.COMPLETED, "正式回复"),))

    with pytest.raises(RuntimeError, match="partial write"):
        await skill.maintain(_invocation(), snapshot, current_profile="", settlement_input_digest="a" * 64)
    turn_seq, profile = await skill.maintain(
        _invocation(), snapshot, current_profile="", settlement_input_digest="a" * 64
    )

    assert (turn_seq, profile) == (1, "喜欢音乐的用户")
    assert memory.extracts == 2
    assert memory.writes == 2
