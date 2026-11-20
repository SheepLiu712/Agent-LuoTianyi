from datetime import datetime, timezone
from uuid import uuid4

import pytest
from support.call_apology import _Plans, _request, _stimulus
from support.reply_skill import make_reply_skill
from support.retrieval import stub_retrieval

import src.domain.agent as d
from src.agent.context.memory_pool import CallMemory
from src.agent.handlers.stimulus.call import (
    CallEndingHandler,
    CallTimeLimitWarningHandler,
)
from src.agent.processing.plan_identity import decode_plan, encode_plan
from src.agent.skills.contracts import ReplyDraft
from src.agent.skills.expression.prepared_speech import PreparedSpeechCatalog
from src.domain import MemoryContext, MemoryHit
from src.domain.call import (
    CallAnswerDecision,
    CallAudioSemantic,
    CallEndReason,
    CallFinalSnapshot,
    CallOutcome,
    CallTerminalFacts,
)


class _Memory:
    def __init__(self):
        self.calls = []

    async def search_memory_context_for_topic(self, user_id, queries):
        self.calls.append((user_id, queries))
        return MemoryContext(
            (
                MemoryHit("旧记忆", 0.9, queries[0], vector_id="one"),
                MemoryHit("新记忆", 0.8, queries[0], vector_id="two"),
            )
        )


class _Generator:
    async def generate(self, **kwargs):
        return (
            ReplyDraft("正式回答", "正式回答", "normal", None),
            ReplyDraft("不应演唱", "不应演唱", "normal", None, sing=("song", "segment")),
        )


def test_answer_call_uuid_plan_round_trips_without_string_coercion():
    call_id = uuid4()
    plan = d.ActionPlan(
        plan_id="plan",
        origin_request_id="request",
        plan_ordinal=0,
        target_character_id="luotianyi",
        interaction_id="call",
        basis_interaction_revision=0,
        source_stimulus_ids=("stimulus",),
        actions=(d.AnswerCall(action_id="answer", call_id=call_id, decision=CallAnswerDecision.ACCEPT),),
    )

    decoded = decode_plan(encode_plan(plan))

    assert decoded == plan
    assert decoded.actions[0].call_id is not None
    assert isinstance(decoded.actions[0].call_id, type(call_id))


@pytest.mark.asyncio
async def test_time_limit_warning_uses_fixed_agent_plan_without_generation():
    handler = CallTimeLimitWarningHandler()
    request = _request(_stimulus(d.CallTimeLimitWarning, call_id=uuid4(), remaining_ms=30_000))
    plans = _Plans()

    report = await handler.handle(request, plans)

    assert report.emitted_plan_ids == ("plan-1",)
    action = plans.drafts[0].actions[0]
    assert isinstance(action, d.Say)
    assert action.content == "通话时间快到了，我们很快就要结束啦。"
    assert action.call_delivery.display_in_chat is False
    assert action.call_delivery.provisional is False


@pytest.mark.asyncio
async def test_call_ending_emits_one_finalize_action_and_keeps_context_alive():
    call_id = uuid4()
    plans = _Plans()
    plans.context.call_memory.remember_hits(
        (MemoryHit("旧记忆", 1, "query", vector_id="one"), MemoryHit("新记忆", 1, "query", vector_id="two"))
    )
    ending = _stimulus(
        d.CallEnding,
        call_id=call_id,
        reason=CallEndReason.USER_HANGUP,
        final_snapshot=CallFinalSnapshot(
            terminal=CallTerminalFacts(
                call_id,
                CallOutcome.CONNECTED,
                CallEndReason.USER_HANGUP,
                1000,
                datetime.now(timezone.utc),
            ),
            completed_turns=(),
            maintenance_turn_seq=0,
        ),
    )
    report = await CallEndingHandler().handle(_request(ending), plans)

    assert report.emitted_plan_ids == ("plan-1",)
    assert len(plans.drafts) == 1
    assert len(plans.drafts[0].actions) == 1
    assert isinstance(plans.drafts[0].actions[0], d.FinalizeCall)
    assert plans.drafts[0].actions[0].final_snapshot is ending.final_snapshot
    assert tuple(item.content for item in plans.context.call_memory.snapshot()) == ("旧记忆", "新记忆")
