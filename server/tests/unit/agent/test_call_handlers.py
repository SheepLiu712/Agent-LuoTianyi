from support.retrieval import stub_retrieval
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from support.call_apology import _Plans, _request, _stimulus
from support.reply_skill import make_reply_skill

import src.domain.agent as d
from src.agent.context.memory_pool import CallMemory
from src.agent.handlers.stimulus.call import (
    CallEndingHandler,
    CallStartedHandler,
    CallReplyRequestedHandler,
    CallSilenceElapsedHandler,
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
async def test_each_formal_request_recalls_without_ack_and_reuses_memory_pool():
    class CapturingGenerator(_Generator):
        async def generate(self, **kwargs):
            assert kwargs["scene"] == "call"
            self.memory_hits = kwargs["memory_hits"]
            return await super().generate(**kwargs)

    memory = _Memory()
    generator = CapturingGenerator()
    recall = stub_retrieval({"luotianyi": memory})
    handler = CallReplyRequestedHandler(
        recall, make_reply_skill({"luotianyi": generator}), PreparedSpeechCatalog({})
    )
    plans = _Plans()
    plans.context.call_memory.remember(CallMemory("previous", "前轮记忆"))
    call_id = uuid4()

    for turn_seq in (1, 2):
        request = _request(
            _stimulus(
                d.CallReplyRequested,
                call_id=call_id,
                turn_seq=turn_seq,
                audio_content=CallAudioSemantic(transcript="你还记得吗"),
            )
        )
        report = await handler.handle(request, plans)
        assert report.request_status is d.HandlingRequestStatus.COMPLETED

    actions = [action for draft in plans.drafts for action in draft.actions]
    assert len(memory.calls) == 2
    assert [action.content for action in actions] == ["正式回答", "正式回答"]
    assert all(not action.call_delivery.provisional for action in actions)
    assert generator.memory_hits == ["前轮记忆", "旧记忆", "新记忆"]
    assert tuple(item.content for item in plans.context.call_memory.snapshot()) == tuple(generator.memory_hits)


async def test_valid_silence_opens_new_topic_without_waiting_or_ending_the_call():
    class Generator(_Generator):
        async def generate(self, **kwargs):
            assert kwargs["scene"] == "call"
            assert "一句简短、口语化" in kwargs["reply_topic"]
            assert "主动开启" in kwargs["reply_topic"]
            return await super().generate(**kwargs)
    handler = CallSilenceElapsedHandler(stub_retrieval({"luotianyi": _Memory()}),
        make_reply_skill({"luotianyi": Generator()}), PreparedSpeechCatalog({}))
    plans = _Plans()
    for _ in range(3):
        report = await handler.handle(_request(_stimulus(d.CallSilenceElapsed, call_id=uuid4(), silence_ms=5000)), plans)
        assert report.request_status is d.HandlingRequestStatus.COMPLETED
    actions = [action for plan in plans.drafts for action in plan.actions]
    assert len(actions) == 3
    assert all(isinstance(action, d.Say) for action in actions)


async def test_call_retrieval_failure_uses_existing_memory_as_the_call_spec_requires():
    class Memory:
        async def search_memory_context_for_topic(self, *args):
            raise RuntimeError("检索不可用")
    class Generator(_Generator):
        async def generate(self, **kwargs):
            assert kwargs["memory_hits"] == ["已有记忆"]
            return await super().generate(**kwargs)
    handler = CallReplyRequestedHandler(stub_retrieval({"luotianyi": Memory()}),
        make_reply_skill({"luotianyi": Generator()}), PreparedSpeechCatalog({}))
    plans = _Plans()
    plans.context.call_memory.remember(CallMemory("old", "已有记忆"))
    report = await handler.handle(_request(_stimulus(d.CallReplyRequested, call_id=uuid4(), turn_seq=1,
        audio_content=CallAudioSemantic(transcript="继续聊天"))), plans)
    assert report.request_status is d.HandlingRequestStatus.COMPLETED
    assert plans.drafts[0].actions[0].content == "正式回答"








@pytest.mark.asyncio
async def test_call_ending_emits_one_finalize_action_and_keeps_context_alive():
    call_id = uuid4()
    plans = _Plans()
    plans.context.call_memory.remember_hits((MemoryHit("旧记忆", 1, "query", vector_id="one"), MemoryHit("新记忆", 1, "query", vector_id="two")))
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


async def test_call_opening_requests_one_short_spoken_greeting():
    class Generator(_Generator):
        async def generate(self, **kwargs):
            assert kwargs["scene"] == "call"
            assert "一句简短、口语化" in kwargs["reply_topic"]
            return await super().generate(**kwargs)

    handler = CallStartedHandler(make_reply_skill({"luotianyi": Generator()}), PreparedSpeechCatalog({}))
    plans = _Plans()
    report = await handler.handle(_request(_stimulus(d.CallStarted, call_id=uuid4(), connected_at=datetime.now(timezone.utc))), plans)
    assert report.request_status is d.HandlingRequestStatus.COMPLETED
    assert plans.drafts[0].actions[0].content == "正式回答"
