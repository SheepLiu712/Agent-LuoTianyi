from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

import src.domain.agent as d
from src.agent import Agent
from src.agent.context import ConversationSnapshot, UserContextSnapshot
from src.agent.handlers.action.call import EndCallHandler
from src.agent.handlers.action.router import ActionRouter
from src.agent.handlers.action.say import SayHandler
from src.agent.handlers.stimulus.call import CallEndingHandler, CallSilenceElapsedHandler, CallTurnCompletedHandler
from src.agent.handlers.stimulus.router import StimulusRouter
from src.agent.processing.plan_identity import decode_plan, encode_plan
from src.agent.skills.cognitive.call_recall import CallRecallDecisionSkill, CallReplySkill, SilenceDecision
from src.agent.skills.contracts import ReplyDraft
from src.domain import MemoryContext, MemoryHit
from src.domain.call import (
    AckStyle,
    CallAnswerDecision,
    CallAudioSemantic,
    CallEndReason,
    CallFinalSnapshot,
    CallOutcome,
    CallRecallDecision,
    CallState,
    CallTerminalFacts,
    RecallMode,
)


class _Conversation:
    def __init__(self):
        self.entries = []

    def read(self):
        return ConversationSnapshot(entries=tuple(self.entries))

    async def append(self, entries):
        self.entries.extend(entries)


class _Plans:
    def __init__(self):
        self.accepted_ids = []
        self.drafts = []
        self.context = SimpleNamespace(
            identity=SimpleNamespace(character_id="luotianyi", user_id="user", interaction_id="call"),
            user=SimpleNamespace(read=lambda: UserContextSnapshot()),
            conversation=_Conversation(),
        )

    async def emit(self, draft):
        self.drafts.append(draft)
        self.accepted_ids.append(f"plan-{len(self.drafts)}")


class _PlanSink:
    def __init__(self):
        self.plans = []

    async def emit(self, plan):
        self.plans.append(plan)
        return d.PlanReceipt(plan_id=plan.plan_id, status=d.PlanAcceptanceStatus.ACCEPTED)


class _SpeechStream:
    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration

    async def aclose(self):
        return None


class _Speaking:
    def speak(self, invocation, *, text, tone):
        _ = invocation, text, tone
        return _SpeechStream()


class _OutputSink:
    def __init__(self):
        self.outputs = []

    async def emit(self, output):
        self.outputs.append(output)
        return d.OutputReceipt(
            execution_id=output.execution_id,
            sequence_no=output.sequence_no,
            status=d.OutputAcceptanceStatus.ACCEPTED,
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


def _request(stimulus):
    return d.HandleStimulusRequest(
        request_id="request",
        stimulus=stimulus,
        interaction=d.CallInteractionSnapshot(
            interaction_id="call",
            interaction_revision=1,
            user_id="user",
            pending_stimuli=(),
            now=datetime.now(timezone.utc),
            timezone=ZoneInfo("UTC"),
            supported_outputs=frozenset({d.AgentOutputKind.AUDIO_CHUNK, d.AgentOutputKind.MESSAGE_END}),
            call_id=stimulus.call_id,
            state=CallState.ACTIVE,
            connection_state=d.ConnectionState.CONNECTED,
        ),
        cancellation=d.CancellationToken(),
    )


def _stimulus(cls, **kwargs):
    return cls(
        stimulus_id="stimulus",
        schema_version=1,
        occurred_at=datetime.now(timezone.utc),
        source=d.StimulusSource.STAGE,
        target_character_ids=("luotianyi",),
        user_id="user",
        ephemeral=True,
        **kwargs,
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
async def test_recall_turn_emits_provisional_then_formal_hidden_call_speech_and_updates_pool_once():
    memory = _Memory()
    recall = CallRecallDecisionSkill(memories={"luotianyi": memory})

    async def decide(*args, **kwargs):
        return CallRecallDecision(RecallMode.RECALL, ("喜欢什么",), AckStyle.THINKING)

    recall.decide = decide
    handler = CallTurnCompletedHandler(recall, CallReplySkill({"luotianyi": _Generator()}))
    call_id = uuid4()
    request = _request(
        _stimulus(
            d.CallTurnCompleted,
            call_id=call_id,
            turn_seq=1,
            audio_content=CallAudioSemantic(transcript="你还记得吗"),
        )
    )
    plans = _Plans()

    report = await handler.handle(request, plans)

    assert report.emitted_plan_ids == ("plan-1", "plan-2")
    assert len(memory.calls) == 1
    assert recall.pool_texts(call_id) == ("旧记忆", "新记忆")
    provisional = plans.drafts[0].actions[0]
    formal = plans.drafts[1].actions[0]
    assert provisional.call_delivery.provisional is True
    assert formal.call_delivery.provisional is False
    assert formal.call_delivery.display_in_chat is False
    assert formal.call_delivery.is_ephemeral is True
    assert formal.message_id is None
    assert all(isinstance(action, d.Say) for draft in plans.drafts for action in draft.actions)
    assert [entry.content.text for entry in plans.context.conversation.entries] == [
        "用户说：“你还记得吗”",
        "正式回答",
    ]


@pytest.mark.asyncio
async def test_silence_end_call_places_farewell_before_end_action():
    recall = CallRecallDecisionSkill(memories={"luotianyi": _Memory()})

    async def decide_silence(*args, **kwargs):
        return SilenceDecision.END_CALL

    recall.decide_silence = decide_silence
    handler = CallSilenceElapsedHandler(recall, CallReplySkill({"luotianyi": _Generator()}))
    request = _request(_stimulus(d.CallSilenceElapsed, call_id=uuid4(), silence_ms=5000))
    plans = _Plans()

    await handler.handle(request, plans)

    assert isinstance(plans.drafts[0].actions[0], d.Say)
    assert isinstance(plans.drafts[0].actions[-1], d.EndCall)
    assert plans.drafts[0].actions[-1].reason is CallEndReason.AGENT_HANGUP


@pytest.mark.asyncio
async def test_real_agent_handle_plan_emitter_and_realize_execute_call_end_flow():
    recall = CallRecallDecisionSkill(memories={"luotianyi": _Memory()})

    async def decide_silence(*args, **kwargs):
        return SilenceDecision.END_CALL

    recall.decide_silence = decide_silence
    agent = Agent(
        character_id="luotianyi",
        stimulus_router=StimulusRouter(
            (
                (
                    d.StimulusKind.CALL_SILENCE_ELAPSED,
                    CallSilenceElapsedHandler(recall, CallReplySkill({"luotianyi": _Generator()})),
                ),
            )
        ),
        action_router=ActionRouter(
            (
                (d.ActionKind.SAY, SayHandler("luotianyi", _Speaking(), SimpleNamespace())),
                (d.ActionKind.END_CALL, EndCallHandler()),
            )
        ),
    )
    request = _request(_stimulus(d.CallSilenceElapsed, call_id=uuid4(), silence_ms=5000))
    plan_sink = _PlanSink()
    interaction_context = _Plans().context

    handling = await agent.handle_stimulus(request, plan_sink, context=interaction_context)

    assert handling.request_status is d.HandlingRequestStatus.COMPLETED
    assert len(plan_sink.plans) == 1
    assert isinstance(plan_sink.plans[0].actions[-1], d.EndCall)
    output_sink = _OutputSink()
    execution = await agent.realize_action_plan(
        plan_sink.plans[0],
        d.ExecutionContext(
            execution_id="execution",
            interaction_id="call",
            current_interaction_revision=1,
            cancellation=d.CancellationToken(),
            interaction_context=interaction_context,
        ),
        output_sink,
    )

    assert execution.status is d.ExecutionStatus.COMPLETED
    assert [result.status for result in execution.action_results] == [
        d.ActionExecutionStatus.COMPLETED,
        d.ActionExecutionStatus.COMPLETED,
    ]
    assert len(output_sink.outputs) == 1
    assert isinstance(output_sink.outputs[0], d.MessageEndOutput)
    assert output_sink.outputs[0].call_delivery.audio_route.value == "CALL"


@pytest.mark.asyncio
async def test_call_ending_does_not_fake_maintenance_or_release_pool_before_settlement():
    memory = _Memory()
    recall = CallRecallDecisionSkill(memories={"luotianyi": memory})
    call_id = uuid4()
    await recall.recall_once(
        SimpleNamespace(character_id="luotianyi", require_user_id=lambda: "user"),
        call_id=call_id,
        queries=("query",),
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
    plans = _Plans()

    report = await CallEndingHandler().handle(_request(ending), plans)

    assert report.emitted_plan_ids == ()
    assert plans.drafts == []
    assert recall.pool_texts(call_id) == ("旧记忆", "新记忆")


@pytest.mark.asyncio
async def test_release_call_memory_is_identity_checked_idempotent_and_call_isolated():
    memory = _Memory()
    recall = CallRecallDecisionSkill(memories={"luotianyi": memory})
    first_call = uuid4()
    second_call = uuid4()
    invocation = SimpleNamespace(character_id="luotianyi", require_user_id=lambda: "user")
    await recall.recall_once(invocation, call_id=first_call, queries=("first",))
    await recall.recall_once(invocation, call_id=second_call, queries=("second",))

    assert recall.release_call_memory(first_call) is True
    assert recall.release_call_memory(first_call) is False
    assert recall.pool_texts(first_call) == ()
    assert recall.pool_texts(second_call) == ("旧记忆", "新记忆")
    with pytest.raises(TypeError, match="UUID"):
        recall.release_call_memory(str(second_call))


@pytest.mark.asyncio
async def test_provisional_ack_is_not_appended_to_ephemeral_formal_facts():
    memory = _Memory()
    recall = CallRecallDecisionSkill(memories={"luotianyi": memory})

    async def decide(*args, **kwargs):
        return CallRecallDecision(RecallMode.RECALL, ("query",), AckStyle.EMPATHY)

    recall.decide = decide
    plans = _Plans()
    request = _request(
        _stimulus(
            d.CallTurnCompleted,
            call_id=uuid4(),
            turn_seq=1,
            audio_content=CallAudioSemantic(transcript="继续说"),
        )
    )

    await CallTurnCompletedHandler(recall, CallReplySkill({"luotianyi": _Generator()})).handle(request, plans)

    assert plans.drafts[0].actions[0].call_delivery.provisional is True
    assert [entry.content.text for entry in plans.context.conversation.entries] == [
        "用户说：“继续说”",
        "正式回答",
    ]
