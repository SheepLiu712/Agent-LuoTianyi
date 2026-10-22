"""One ending plan, sequential cognition, and current-call-only fallback."""

from types import SimpleNamespace

import pytest

import src.domain.agent as d
from src.agent.context import ContextIdentity, ConversationContext, ConversationSnapshot, ConversationSummary
from src.agent.context._conversation_store import EphemeralCallConversationStore
from src.agent.handlers.action.call_settlement import FinalizeCallHandler
from src.agent.ledgers._execution_codec import ActionFact, decode_facts, encode_facts
from src.agent.processing.plan_identity import decode_plan, encode_plan
from src.agent.skills.cognitive.call_settlement import CallSummarySkill
from src.domain.call import CallFinalTurn, CallReplyStatus, CallSummarySource

from .test_call_settlement_skills import _snapshot


@pytest.mark.asyncio
@pytest.mark.parametrize("maintenance_fails", [False, True])
@pytest.mark.parametrize(
    "response,working,expected,source",
    [
        ("new final", "old working", "new final", CallSummarySource.GENERATED),
        (TimeoutError(), "current call summary", "current call summary", CallSummarySource.CONTEXT),
        (TimeoutError(), "", "[和用户打了一通电话]", CallSummarySource.DEFAULT),
        ("", "keep " * 60, "keep " * 60, CallSummarySource.CONTEXT),
        ("x" * 201, "", "[和用户打了一通电话]", CallSummarySource.DEFAULT),
        (None, "", "[和用户打了一通电话]", CallSummarySource.DEFAULT),
    ],
)
async def test_finalize_maintains_then_summarizes_with_three_level_fallback(
    maintenance_fails, response, working, expected, source
):
    conversation = ConversationContext(
        identity=ContextIdentity("luotianyi", "call", "user"),
        _store=EphemeralCallConversationStore(
            ConversationSnapshot(ConversationSummary("seed must never become final"))
        ),
    )
    if working:
        await conversation.update_call_working_summary(ConversationSummary(working))
    context = SimpleNamespace(conversation=conversation)
    calls = []

    class Maintenance:
        async def maintain_ending(self, invocation, supplied, snapshot):
            assert supplied is context
            calls.append("maintenance")
            if maintenance_fails:
                raise TimeoutError("attempts exhausted")
            conversation.advance_call_maintenance_progress(expected=0, new=1)

    class Model:
        async def generate_response(self, **kwargs):
            assert calls == ["maintenance"]
            calls.append("summary")
            if isinstance(response, Exception):
                raise response
            return response

    skill = CallSummarySkill({"luotianyi": Model()} if response is not None else {})
    snapshot = _snapshot(turns=(CallFinalTurn(1, "fact", CallReplyStatus.NOT_STARTED, None),))
    action = d.FinalizeCall(action_id="finalize", user_id="user", final_snapshot=snapshot)
    execution = d.ExecutionContext(
        execution_id="execution",
        interaction_id="call",
        current_interaction_revision=0,
        cancellation=d.CancellationToken(),
        interaction_context=context,
    )
    result = await FinalizeCallHandler("luotianyi", Maintenance(), skill).realize(action, execution, None)
    assert result.call_ending.summary == expected
    assert result.call_ending.summary_source is source
    assert result.call_ending.maintenance_succeeded is not maintenance_fails
    assert result.call_ending.maintenance_turn_seq == (0 if maintenance_fails else 1)
    assert calls == (["maintenance"] if response is None else ["maintenance", "summary"])
    plan = d.ActionPlan(
        plan_id="plan",
        origin_request_id="request",
        plan_ordinal=0,
        target_character_id="luotianyi",
        interaction_id="call",
        basis_interaction_revision=0,
        source_stimulus_ids=("ending",),
        actions=(action,),
    )
    assert decode_plan(encode_plan(plan)) == plan
    facts = [ActionFact(started=True, result=result)]
    assert decode_facts(encode_facts(facts), plan) == facts
