"""Real Context/Ephemeral/compaction/action/SQL boundaries; model ports are fakes."""

import asyncio
import threading
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import src.domain.agent as d
from src.agent.context import (
    ContextFactory,
    ContextIdentity,
    ConversationCompaction,
    ConversationContext,
    ConversationEntry,
    ConversationMode,
    ConversationSnapshot,
    ConversationSummary,
    TextContent,
)
from src.agent.context._conversation_store import EphemeralCallConversationStore
from src.agent.handlers.action.call_settlement import FinalizeCallHandler
from src.agent.handlers.action.cognitive_maintenance import CognitiveMaintenanceActionHandler
from src.agent.skills.cognitive.call_settlement import CallMaintenanceSkill, CallSummarySkill
from src.agent.skills.cognitive_maintenance import CognitiveMaintenanceSkill
from src.agent.skills.contracts import SkillInvocation
from src.agent.skills.conversation.compaction import ConversationCompactionSkill
from src.domain.call import (
    CallEndReason,
    CallFinalSnapshot,
    CallFinalTurn,
    CallOutcome,
    CallReplyStatus,
    CallState,
    CallTerminalFacts,
)
from src.domain.call.contracts import CallMaintenanceSnapshot
from src.infrastructure.persistence.call_maintenance import SqlCallMaintenanceBatchRepository
from src.infrastructure.persistence.call_sessions import CallSessionRecord, SettlementStatus
from src.infrastructure.persistence.call_sessions.sql_repository import SqlCallSessionRepository
from src.infrastructure.persistence.database.redis_buffer import RedisBuffer
from src.infrastructure.persistence.database.services.conversation_service import ConversationService
from src.infrastructure.persistence.database.services.user_store import UserStore
from src.infrastructure.persistence.database.sql_database import Base, User


class Memory:
    def __init__(self):
        self.inputs = []
        self.profile_inputs = []
        self.writes = []
        self.failures = 0

    async def extract_maintenance_candidates(self, **kwargs):
        self.inputs.append(kwargs)
        return (d.MaintenanceCandidate(d.MaintenanceMemoryType.USER_FACT, "safe candidate"),)

    async def propose_user_profile(self, **kwargs):
        self.profile_inputs.append(kwargs)
        return "safe profile"

    async def write_maintenance_candidates(self, **kwargs):
        self.writes.append(kwargs)
        if self.failures:
            self.failures -= 1
            raise RuntimeError("write unavailable")


class Profile:
    def __init__(self):
        self.value = ""

    def read(self):
        return SimpleNamespace(profile=SimpleNamespace(description=self.value))

    async def update_profile(self, profile):
        self.value = profile.description


class SummaryModel:
    def __init__(self):
        self.inputs = []

    async def generate_response(self, **kwargs):
        self.inputs.append(kwargs)
        return "private working summary"


class SummaryService:
    def __init__(self, model):
        self.model = model

    def register_llm_module(self, _name, _config):
        return self.model


@pytest.fixture
def setup(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'call.sqlite'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    calls = SqlCallSessionRepository(sessions)
    batches = SqlCallMaintenanceBatchRepository(sessions)
    call_id = uuid4()
    now = datetime.now(timezone.utc)
    record = calls.create_if_absent(
        CallSessionRecord(call_id, "request", "user", "luotianyi", CallState.ACTIVE, now, now, now)
    )
    memory, model = Memory(), SummaryModel()
    call_skill = CallMaintenanceSkill({"luotianyi": memory}, batches)
    compaction = ConversationCompactionSkill(
        {"llm_module": {}}, SimpleNamespace(register_llm_module=lambda *args: model)
    )
    skill = CognitiveMaintenanceSkill(
        memories={"luotianyi": memory}, compaction=compaction, call_maintenance=call_skill
    )
    yield SimpleNamespace(
        engine=engine,
        calls=calls,
        batches=batches,
        record=record,
        memory=memory,
        model=model,
        call_skill=call_skill,
        skill=skill,
    )
    engine.dispose()


def entry(entry_id, index, content, source="user"):
    return ConversationEntry(entry_id, datetime(2026, 1, 1) + timedelta(seconds=index), source, TextContent(content))


async def context_with_turns(seed_count=0, count=32):
    seed = ConversationSnapshot(entries=tuple(entry(f"seed-{i}", i, "old chat secret") for i in range(seed_count)))
    context = SimpleNamespace(
        identity=ContextIdentity("luotianyi", "call", "user"),
        conversation=ConversationContext(
            identity=ContextIdentity("luotianyi", "call", "user"), _store=EphemeralCallConversationStore(seed)
        ),
        user=Profile(),
    )
    turns = []
    for seq in range(1, count + 1):
        await context.conversation.append(
            (
                entry(f"call-turn-{seq}-user", 100 + 2 * seq, f"private user {seq}"),
                entry(f"call-turn-{seq}-agent-0", 101 + 2 * seq, f"private reply {seq}", "agent"),
            )
        )
        turns.append(
            CallFinalTurn(
                seq,
                f"private user {seq}",
                CallReplyStatus.INTERRUPTED if seq == 2 else CallReplyStatus.COMPLETED,
                f"private reply {seq}",
            )
        )
    return context, tuple(turns)


async def threshold(setup, context, turns):
    execution = d.ExecutionContext(
        execution_id="maintenance",
        interaction_id="call",
        current_interaction_revision=0,
        cancellation=d.CancellationToken(),
        interaction_context=context,
        call_maintenance_snapshot=CallMaintenanceSnapshot(setup.record.call_id, turns),
    )
    return await CognitiveMaintenanceActionHandler("luotianyi", setup.skill).realize(
        d.CognitiveMaintenance(action_id="maintenance", reason=d.MaintenanceReason.COMPACTION_THRESHOLD),
        execution,
        None,
    )


def final_snapshot(setup, turns, progress=0):
    return CallFinalSnapshot(
        CallTerminalFacts(
            setup.record.call_id, CallOutcome.CONNECTED, CallEndReason.USER_HANGUP, 1000, datetime.now(timezone.utc)
        ),
        turns,
        progress,
    )


@pytest.mark.asyncio
async def test_final_summary_keeps_accepted_input_missing_from_context_after_ending_maintenance(setup):
    context, turns = await context_with_turns(count=1)
    turns += (CallFinalTurn(2, "accepted but context append failed", CallReplyStatus.NOT_STARTED, None),)
    snapshot = final_snapshot(setup, turns)
    execution = d.ExecutionContext(
        execution_id="ending",
        interaction_id="call",
        current_interaction_revision=0,
        cancellation=d.CancellationToken(),
        interaction_context=context,
    )
    result = await FinalizeCallHandler(
        "luotianyi", setup.call_skill, CallSummarySkill({"luotianyi": setup.model})
    ).realize(d.FinalizeCall(action_id="ending", user_id="user", final_snapshot=snapshot), execution, None)
    assert result.call_ending.maintenance_succeeded
    assert context.conversation.read_call_maintenance_progress() == 2
    inputs = setup.model.inputs[0]["completed_turns"]
    assert sum("accepted but context append failed" in item for item in inputs) == 1
    assert sum("private user 1" in item for item in inputs) == 1
    assert "accepted but context append failed" in setup.memory.inputs[0]["current_dialogue"]


@pytest.mark.asyncio
@pytest.mark.parametrize("seed_count,expected_progress", [(0, 17), (30, 17)])
async def test_threshold_compacts_ephemeral_only_and_ending_maintains_tail(setup, seed_count, expected_progress):
    # Without a seed use 32 turns => 34 covered entries / 17 complete turns.
    context, turns = await context_with_turns(seed_count)
    await threshold(setup, context, turns)
    assert len(context.conversation.read().entries) == seed_count + 30
    assert context.conversation.read_call_maintenance_progress() == expected_progress
    assert setup.calls.find_by_id(setup.record.call_id).maintenance_turn_seq == 0
    assert setup.calls.find_by_id(setup.record.call_id).maintenance_status is SettlementStatus.PENDING
    assert "old chat secret" not in repr(setup.memory.inputs)
    assert "private reply 2\n" not in setup.memory.inputs[0]["current_dialogue"]
    assert "private user 2\n" in setup.memory.inputs[0]["current_dialogue"]
    result = await setup.call_skill.maintain_ending(
        SkillInvocation("luotianyi", "user", "call", d.CancellationToken()),
        context,
        final_snapshot(setup, turns, expected_progress),
    )
    assert result == 32
    assert "private user 17\n" not in setup.memory.inputs[1]["current_dialogue"]
    assert "private user 18\n" in setup.memory.inputs[1]["current_dialogue"]
    with setup.engine.connect() as sql:
        rows = repr(sql.execute(text("SELECT * FROM call_maintenance_batches")).all())
        assert all(
            value not in rows
            for value in ("old chat secret", "private user", "private reply", "private working summary")
        )
        assert sql.execute(text("SELECT count(*) FROM conversations")).scalar() == 0


@pytest.mark.asyncio
async def test_failed_threshold_is_frozen_and_recovered_before_new_ending_tail(setup):
    context, turns = await context_with_turns()
    setup.memory.failures = 2
    with pytest.raises(RuntimeError, match="write unavailable"):
        await threshold(setup, context, turns)
    assert len(setup.memory.inputs) == 1
    assert len(setup.memory.writes) == 2
    assert len(context.conversation.read().entries) == 64
    assert context.conversation.read_call_maintenance_progress() == 0
    # A new stateless Skill instance must recover the frozen prefix from persistence.
    setup.call_skill = CallMaintenanceSkill({"luotianyi": setup.memory}, setup.batches)
    turns += (CallFinalTurn(33, "new user tail", CallReplyStatus.NOT_STARTED, None),)
    result = await setup.call_skill.maintain_ending(
        SkillInvocation("luotianyi", "user", "call", d.CancellationToken()),
        context,
        final_snapshot(setup, turns),
    )
    assert result == 33
    assert len(setup.memory.inputs) == 2
    assert setup.memory.writes[0] == setup.memory.writes[2]
    assert "new user tail" in setup.memory.inputs[1]["current_dialogue"]
    assert "private user 17\n" not in setup.memory.inputs[1]["current_dialogue"]
    assert context.conversation.read_call_maintenance_progress() == 33


@pytest.mark.asyncio
async def test_merged_batch_is_not_split_and_frozen_retry_keeps_one_shared_reply(setup):
    context, turns = await context_with_turns()
    turns = tuple(
        (
            replace(
                turn,
                formal_agent_text=None,
                reply_turn_seq=18,
            )
            if turn.turn_seq in {16, 17}
            else (
                replace(turn, reply_turn_seq=18, confirmed_agent_text="one shared reply")
                if turn.turn_seq == 18
                else turn
            )
        )
        for turn in turns
    )
    setup.memory.failures = 2
    with pytest.raises(RuntimeError, match="write unavailable"):
        await threshold(setup, context, turns)
    # Normal compaction would cover 17 inputs. The 16..18 batch must remain whole.
    assert context.conversation.read_call_maintenance_progress() == 0
    assert "private user 16" not in setup.memory.inputs[0]["current_dialogue"]
    assert len(setup.memory.inputs) == 1
    await threshold(setup, context, turns)
    assert context.conversation.read_call_maintenance_progress() == 15
    assert setup.memory.writes[0] == setup.memory.writes[2]
    assert len(setup.memory.inputs) == 1
    result = await setup.call_skill.maintain_ending(
        SkillInvocation("luotianyi", "user", "call", d.CancellationToken()),
        context,
        final_snapshot(setup, turns, 15),
    )
    assert result == 32
    tail = setup.memory.inputs[1]["current_dialogue"]
    assert "private user 16" in tail and "private user 17" in tail
    assert tail.count("one shared reply") == 1


@pytest.mark.asyncio
async def test_no_maintenance_below_threshold_or_over_unsettled_prefix(setup):
    context, turns = await context_with_turns(count=30)
    await threshold(setup, context, turns)
    assert not setup.memory.inputs
    context, turns = await context_with_turns()
    await threshold(setup, context, turns[:2])
    assert not setup.memory.inputs
    assert len(context.conversation.read().entries) == 64


@pytest.mark.asyncio
async def test_partial_turn_compaction_keeps_both_halves_and_finally_maintains_tail(setup):
    context, turns = await context_with_turns(count=3)
    model = SummaryModel()
    compaction = ConversationCompactionSkill(
        {
            "raw_conversation_context_limit": 5,
            "not_zip_conversation_count": 3,
            "forget_conversation_days": 10,
            "llm_module": {},
        },
        SummaryService(model),
    )
    invocation = SkillInvocation("luotianyi", "user", "call", d.CancellationToken())
    maintenance = CallMaintenanceSnapshot(setup.record.call_id, turns)

    await setup.call_skill.maintain_window(invocation, context, maintenance, compaction=compaction)

    remaining = tuple(entry.entry_id for entry in context.conversation.read_working().entries)
    assert context.conversation.read_call_maintenance_progress() == 1
    assert remaining == (
        "call-turn-2-user",
        "call-turn-2-agent-0",
        "call-turn-3-user",
        "call-turn-3-agent-0",
    )
    assert len(model.inputs) == 1
    assert "private user 1" in model.inputs[0]["recent_conversation"]
    assert "private reply 1" in model.inputs[0]["recent_conversation"]
    assert "private user 2" not in model.inputs[0]["recent_conversation"]

    result = await setup.call_skill.maintain_ending(
        invocation,
        context,
        final_snapshot(setup, turns),
    )
    assert result == 3
    assert "private user 2" in setup.memory.inputs[-1]["current_dialogue"]
    assert "private user 3" in setup.memory.inputs[-1]["current_dialogue"]


@pytest.mark.asyncio
async def test_real_compaction_failure_keeps_progress_and_every_unmaintained_entry(setup):
    class FailingSummaryModel:
        async def generate_response(self, **_kwargs):
            raise RuntimeError("summary unavailable")

    context, turns = await context_with_turns(count=3)
    compaction = ConversationCompactionSkill(
        {
            "raw_conversation_context_limit": 5,
            "not_zip_conversation_count": 3,
            "forget_conversation_days": 10,
            "llm_module": {},
        },
        SummaryService(FailingSummaryModel()),
    )
    invocation = SkillInvocation("luotianyi", "user", "call", d.CancellationToken())
    before = context.conversation.read_working()

    with pytest.raises(RuntimeError, match="summary unavailable"):
        await setup.call_skill.maintain_window(
            invocation,
            context,
            CallMaintenanceSnapshot(setup.record.call_id, turns),
            compaction=compaction,
        )

    after = context.conversation.read_working()
    assert context.conversation.read_call_maintenance_progress() == 0
    assert after == before
    assert setup.memory.inputs == []


@pytest.mark.asyncio
async def test_cancel_during_owned_compaction_does_not_poison_next_batch(setup):
    context, turns = await context_with_turns()
    store = context.conversation._store
    original = store.compact
    admitted, release = threading.Event(), threading.Event()

    def blocked(compaction):
        admitted.set()
        assert release.wait(5)
        original(compaction)

    store.compact = blocked
    task = asyncio.create_task(threshold(setup, context, turns))
    try:
        assert await asyncio.to_thread(admitted.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    store.compact = original
    assert len(context.conversation.read().entries) == 30
    assert context.conversation.read_call_maintenance_progress() == 17
    for seq in range(33, 49):
        await context.conversation.append(
            (
                entry(f"call-turn-{seq}-user", 100 + 2 * seq, f"private user {seq}"),
                entry(f"call-turn-{seq}-agent-0", 101 + 2 * seq, f"private reply {seq}", "agent"),
            )
        )
        turns += (CallFinalTurn(seq, f"private user {seq}", CallReplyStatus.COMPLETED, f"private reply {seq}"),)
    await threshold(setup, context, turns)
    assert len(context.conversation.read().entries) == 30
    assert context.conversation.read_call_maintenance_progress() == 33
    assert len(setup.memory.inputs) == 2


@pytest.mark.asyncio
async def test_factory_seed_is_answer_context_only_after_compaction_and_ending(setup):
    sessions = sessionmaker(bind=setup.engine)
    with sessions() as sql:
        sql.add(User(uuid="user", username="seed-user", password="unused", description=""))
        sql.commit()
    cache = RedisBuffer()
    database = ConversationService(
        sql_session_factory=sessions, redis_buffer=cache, user_store=UserStore({}, sessions, cache)
    )
    factory = ContextFactory(character_id="luotianyi", database=database)
    chat = await factory.create("chat", mode=ConversationMode.CHAT, user_id="user")
    seeds = (entry("e1", 1, "old chat secret one"), entry("e2", 2, "old chat secret two"))
    await chat.conversation.append(seeds)
    await chat.close()
    context = await factory.create(
        "call", mode=ConversationMode.CALL, user_id="user", requested_at=datetime(2026, 1, 1, 0, 1)
    )
    try:
        assert context.conversation.read().entries == seeds
        assert context.conversation.read_working().entries == ()
        await context.conversation.append((entry("c1", 61, "new call one"), entry("c2", 62, "new call two")))
        await context.conversation.compact(
            ConversationCompaction(ConversationSummary(), ("c1",), ConversationSummary("private call working summary"))
        )
        assert [item.entry_id for item in context.conversation.read_working().entries] == ["c2"]
        turns = (
            CallFinalTurn(1, "new call one", CallReplyStatus.NOT_STARTED, None),
            CallFinalTurn(2, "new call two", CallReplyStatus.NOT_STARTED, None),
        )
        result = await setup.call_skill.maintain_ending(
            SkillInvocation("luotianyi", "user", "call", d.CancellationToken()),
            context,
            final_snapshot(setup, turns),
        )
        assert result == 2
        assert "new call one" in setup.memory.inputs[0]["current_dialogue"]
        assert "new call two" in setup.memory.inputs[0]["current_dialogue"]
        assert "old chat secret" not in repr(setup.memory.inputs)
        assert "mixed working summary" not in repr(setup.memory.inputs)
        assert "new call one" in repr(setup.memory.profile_inputs)
        assert "new call two" in repr(setup.memory.profile_inputs)
        assert "old chat secret" not in repr(setup.memory.profile_inputs)
        assert "mixed working summary" not in repr(setup.memory.profile_inputs)
    finally:
        await context.close()
    restored = await factory.create("restored", mode=ConversationMode.CHAT, user_id="user")
    assert restored.conversation.read().entries == seeds
    await restored.close()
