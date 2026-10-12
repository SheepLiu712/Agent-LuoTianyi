from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from support.context_support import entry
from support.skill_support import invocation

from src.agent.context import ContextFactory, ConversationCompaction, ConversationSummary
from src.agent.skills.cognitive_maintenance import CognitiveMaintenanceSkill
from src.domain.agent.maintenance import (
    MaintenanceCandidate,
    MaintenanceMemoryType,
    MaintenanceReason,
    MaintenanceStatus,
)
from src.infrastructure.persistence.database.redis_buffer import RedisBuffer
from src.infrastructure.persistence.database.services.conversation_service import ConversationService
from src.infrastructure.persistence.database.services.user_store import UserStore
from src.infrastructure.persistence.database.sql_database import Base, User


@pytest.fixture
def database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'maintenance-review.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as session:
        session.add(User(uuid="u", username="user", password="unused", description="画像"))
        session.commit()
    cache = RedisBuffer()
    service = ConversationService(
        sql_session_factory=sessions,
        redis_buffer=cache,
        user_store=UserStore({}, sessions, cache),
    )
    yield service
    engine.dispose()


class RecordingMemory:
    def __init__(self, *, fail_first_write: bool = False, append_during_first_write=None) -> None:
        self.fail_first_write = fail_first_write
        self.append_during_first_write = append_during_first_write
        self.extracts: list[str] = []
        self.writes: list[tuple[str, tuple[MaintenanceCandidate, ...]]] = []
        self.profile_inputs: list[list[str]] = []

    async def extract_maintenance_candidates(self, *, history, current_dialogue):
        self.extracts.append(current_dialogue)
        return (MaintenanceCandidate(MaintenanceMemoryType.USER_FACT, current_dialogue),)

    async def write_maintenance_candidates(self, *, user_id, maintenance_id, candidates):
        if self.append_during_first_write is not None:
            append = self.append_during_first_write
            self.append_during_first_write = None
            await append()
        if self.fail_first_write:
            self.fail_first_write = False
            raise RuntimeError("projection failed")
        self.writes.append((maintenance_id, candidates))

    async def propose_user_profile(self, *, history, current_profile):
        self.profile_inputs.append(history["recent_conversation"])
        return None


class PrefixCompaction:
    def requires_compaction(self, conversation) -> bool:
        return len(conversation.read().entries) > 60

    async def compact(self, conversation):
        snapshot = conversation.read()
        covered = snapshot.entries[:-30]
        return ConversationCompaction(
            snapshot.summary,
            tuple(item.entry_id for item in covered),
            ConversationSummary("压缩总结"),
        )


class AppendingPrefixCompaction(PrefixCompaction):
    def __init__(self, append) -> None:
        self._append = append
        self.calls = []

    async def compact(self, conversation):
        if self._append is not None:
            append = self._append
            self._append = None
            await append()
        result = await super().compact(conversation)
        self.calls.append(conversation.read())
        return result


def skill(memory):
    return CognitiveMaintenanceSkill(memories={"luotianyi": memory}, compaction=PrefixCompaction())


async def context_with(database, numbers):
    context = await ContextFactory(character_id="luotianyi", database=database).create("interaction", user_id="u")
    await context.conversation.append(tuple(entry(number) for number in numbers))
    return context


@pytest.mark.asyncio
async def test_second_short_interaction_covers_history_but_maintains_only_new_entries(database):
    memory = RecordingMemory()
    first = await context_with(database, (1, 2))
    first_report = await skill(memory).maintain(invocation(), first, reason=MaintenanceReason.INTERACTION_ENDING)
    assert first_report.status is MaintenanceStatus.COMPLETED
    await first.close()

    second = await context_with(database, (3, 4))
    second_report = await skill(memory).maintain(invocation(), second, reason=MaintenanceReason.INTERACTION_ENDING)

    assert second_report.status is MaintenanceStatus.COMPLETED
    assert second_report.previous_progress == "2"
    assert second_report.new_progress == "4"
    assert second_report.covered_entry_ids == ("1", "2", "3", "4")
    assert second_report.maintained_entry_ids == ("3", "4")
    assert memory.extracts[-1] == "user: 消息3\nuser: 消息4"
    assert memory.profile_inputs[-1] == ["user: 消息3", "user: 消息4"]
    await second.close()


@pytest.mark.asyncio
async def test_threshold_compacts_prefix_after_marker_without_reextracting_history(database):
    memory = RecordingMemory()
    initial = await context_with(database, range(1, 61))
    ended = await skill(memory).maintain(invocation(), initial, reason=MaintenanceReason.INTERACTION_ENDING)
    assert ended.new_progress == "60"
    await initial.close()

    resumed = await context_with(database, (61,))
    threshold = await skill(memory).maintain_if_compaction_needed(invocation(), resumed)

    assert threshold.status is MaintenanceStatus.COMPLETED
    assert threshold.compacted is True
    assert threshold.covered_entry_ids == tuple(str(index) for index in range(1, 32))
    assert threshold.maintained_entry_ids == ()
    assert threshold.new_progress == "60"
    assert len(memory.extracts) == 1
    snapshot = resumed.conversation.read()
    assert snapshot.summary == ConversationSummary("压缩总结")
    assert tuple(item.entry_id for item in snapshot.entries) == tuple(str(index) for index in range(32, 62))

    final = await skill(memory).maintain(invocation(), resumed, reason=MaintenanceReason.INTERACTION_ENDING)
    assert final.status is MaintenanceStatus.COMPLETED
    assert final.new_progress == "61"
    assert final.maintained_entry_ids == ("61",)
    assert memory.extracts[-1] == "user: 消息61"
    await resumed.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("progress", "expected_maintained"),
    [("15", tuple(str(index) for index in range(16, 32))), ("31", ())],
)
async def test_threshold_locates_marker_in_full_snapshot_for_inside_and_after_prefix(
    database, progress, expected_maintained
):
    memory = RecordingMemory()
    context = await context_with(database, range(1, 62))
    assert database.advance_cognitive_maintenance_progress(
        "u", character_id="luotianyi", expected_entry_id=None, new_entry_id=progress
    )

    report = await skill(memory).maintain_if_compaction_needed(invocation(), context)

    assert report.status is MaintenanceStatus.COMPLETED
    assert report.maintained_entry_ids == expected_maintained
    assert report.new_progress == ("31" if expected_maintained else progress)
    assert tuple(item.entry_id for item in context.conversation.read().entries) == tuple(str(i) for i in range(32, 62))
    await context.close()


@pytest.mark.asyncio
async def test_ending_maintains_long_snapshot_through_tail(database):
    memory = RecordingMemory()
    context = await context_with(database, range(1, 62))

    report = await skill(memory).maintain(invocation(), context, reason=MaintenanceReason.INTERACTION_ENDING)

    assert report.status is MaintenanceStatus.COMPLETED
    assert report.new_progress == "61"
    assert await context.conversation.read_maintenance_progress() == "61"
    assert len(memory.extracts) == 2
    assert "消息31" in memory.extracts[0]
    assert "消息32" in memory.extracts[1]
    assert "消息61" in memory.extracts[1]
    await context.close()


@pytest.mark.asyncio
async def test_ending_resumes_frozen_batch_then_maintains_next_interaction_tail(database):
    memory = RecordingMemory(fail_first_write=True)
    first = await context_with(database, (1, 2))
    with pytest.raises(RuntimeError, match="projection failed"):
        await skill(memory).maintain(invocation(), first, reason=MaintenanceReason.INTERACTION_ENDING)
    await first.close()

    second = await context_with(database, (3, 4))
    report = await skill(memory).maintain(invocation(), second, reason=MaintenanceReason.INTERACTION_ENDING)

    assert report.status is MaintenanceStatus.COMPLETED
    assert report.new_progress == "4"
    assert await second.conversation.read_maintenance_progress() == "4"
    assert len(memory.extracts) == 2
    assert memory.extracts == ["user: 消息1\nuser: 消息2", "user: 消息3\nuser: 消息4"]
    assert len(memory.writes) == 2
    assert memory.writes[0][0] != memory.writes[1][0]
    await second.close()


@pytest.mark.asyncio
async def test_ending_uses_fixed_snapshot_boundary_when_new_entries_arrive(database):
    context = await context_with(database, range(1, 62))

    async def append_late_entry():
        await context.conversation.append((entry(62),))

    memory = RecordingMemory(append_during_first_write=append_late_entry)
    report = await skill(memory).maintain(invocation(), context, reason=MaintenanceReason.INTERACTION_ENDING)

    assert report.new_progress == "61"
    assert await context.conversation.read_maintenance_progress() == "61"
    assert "消息62" not in "\n".join(memory.extracts)
    assert context.conversation.read().entries[-1].entry_id == "62"
    await context.close()


@pytest.mark.asyncio
async def test_ending_compaction_freezes_model_input_and_defers_late_entries(database):
    context = await context_with(database, range(1, 62))

    async def append_late_entries():
        await context.conversation.append(tuple(entry(number) for number in range(62, 93)))

    compaction = AppendingPrefixCompaction(append_late_entries)
    memory = RecordingMemory()
    maintenance = CognitiveMaintenanceSkill(memories={"luotianyi": memory}, compaction=compaction)

    initial = await maintenance.maintain(invocation(), context, reason=MaintenanceReason.INTERACTION_ENDING)

    assert initial.status is MaintenanceStatus.COMPLETED
    assert initial.new_progress == "61"
    assert initial.covered_entry_ids == tuple(str(number) for number in range(1, 62))
    assert initial.maintained_entry_ids == tuple(str(number) for number in range(1, 62))
    assert await context.conversation.read_maintenance_progress() == "61"
    assert len(compaction.calls) == 1
    assert tuple(item.entry_id for item in compaction.calls[0].entries) == tuple(str(number) for number in range(1, 62))
    assert all("消息62" not in dialogue for dialogue in memory.extracts)
    assert all("消息62" not in "\n".join(lines) for lines in memory.profile_inputs)

    resumed = await maintenance.maintain(invocation(), context, reason=MaintenanceReason.INTERACTION_ENDING)

    assert resumed.status is MaintenanceStatus.COMPLETED
    assert resumed.previous_progress == "61"
    assert resumed.new_progress == "92"
    assert await context.conversation.read_maintenance_progress() == "92"
    assert memory.extracts[-1].endswith("消息92")
    await context.close()


@pytest.mark.asyncio
async def test_empty_ending_boundary_does_not_absorb_entries_appended_before_batch_read(database):
    context = await context_with(database, ())
    memory = RecordingMemory()
    original_read_progress = context.conversation.read_maintenance_progress

    async def append_before_batch_read():
        await context.conversation.append((entry(1), entry(2)))
        return await original_read_progress()

    context.conversation.read_maintenance_progress = append_before_batch_read
    first = await skill(memory).maintain(invocation(), context, reason=MaintenanceReason.INTERACTION_ENDING)

    assert first.status is MaintenanceStatus.SKIPPED
    assert first.new_progress is None
    assert memory.extracts == []
    assert memory.profile_inputs == []
    assert await context.conversation.read_maintenance_progress() is None

    context.conversation.read_maintenance_progress = original_read_progress
    second = await skill(memory).maintain(invocation(), context, reason=MaintenanceReason.INTERACTION_ENDING)

    assert second.status is MaintenanceStatus.COMPLETED
    assert second.new_progress == "2"
    assert memory.extracts == ["user: 消息1\nuser: 消息2"]
    await context.close()


@pytest.mark.asyncio
async def test_empty_ending_boundary_does_not_resume_an_existing_frozen_batch(database):
    empty = await context_with(database, ())
    failed = await context_with(database, (1, 2))
    with pytest.raises(RuntimeError, match="projection failed"):
        await skill(RecordingMemory(fail_first_write=True)).maintain(
            invocation(), failed, reason=MaintenanceReason.INTERACTION_ENDING
        )
    await failed.close()

    memory = RecordingMemory()
    report = await skill(memory).maintain(invocation(), empty, reason=MaintenanceReason.INTERACTION_ENDING)

    assert report.status is MaintenanceStatus.SKIPPED
    assert report.new_progress is None
    assert memory.extracts == []
    assert memory.profile_inputs == []
    assert memory.writes == []
    assert await empty.conversation.read_maintenance_progress() is None
    await empty.close()


@pytest.mark.asyncio
async def test_missing_ending_boundary_conflicts_without_processing_current_tail(database):
    context = await context_with(database, range(1, 62))
    concurrent = await context_with(database, ())
    initial_snapshot = context.conversation.read()
    await concurrent.conversation.compact(
        ConversationCompaction(
            initial_snapshot.summary,
            tuple(item.entry_id for item in initial_snapshot.entries),
            ConversationSummary("并发压缩总结"),
        )
    )
    memory = RecordingMemory()
    reads = iter((initial_snapshot, concurrent.conversation.read()))
    context.conversation.read = lambda: next(reads)

    report = await skill(memory).maintain(invocation(), context, reason=MaintenanceReason.INTERACTION_ENDING)

    assert report.status is MaintenanceStatus.CONFLICT
    assert report.new_progress is None
    assert memory.extracts == []
    assert memory.profile_inputs == []
    assert await concurrent.conversation.read_maintenance_progress() is None
    await context.close()
    await concurrent.close()
