from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from support.skill_support import invocation

import src.domain.agent as d
from src.agent.context import (
    ConversationCompaction,
    ConversationEntry,
    ConversationSnapshot,
    ConversationSummary,
    TextContent,
    UserContextSnapshot,
    UserProfile,
)
from src.agent.skills.cognitive_maintenance import CognitiveMaintenanceSkill
from src.domain.agent.maintenance import (
    MaintenanceCandidate,
    MaintenanceMemoryType,
    MaintenanceReason,
    MaintenanceStatus,
)
from src.infrastructure.persistence.cognitive_maintenance import CognitiveMaintenanceBatch


def entry(number: int) -> ConversationEntry:
    return ConversationEntry(
        f"e{number}",
        datetime(2026, 10, 9) + timedelta(seconds=number),
        "user" if number % 2 else "agent",
        TextContent(f"消息{number}"),
    )


class Conversation:
    def __init__(self, entries=(), progress=None, *, cas=True):
        self.snapshot = ConversationSnapshot(ConversationSummary("旧总结"), tuple(entries))
        self.progress = progress
        self.cas = cas
        self.compactions = []
        self.batch = None

    def read(self):
        return self.snapshot

    async def read_maintenance_progress(self):
        return self.progress

    async def advance_maintenance_progress(self, *, expected_entry_id, new_entry_id):
        if not self.cas or self.progress != expected_entry_id:
            return False
        self.progress = new_entry_id
        return True

    async def compact(self, value):
        self.compactions.append(value)

    async def load_cognitive_maintenance_batch(self, *, previous_progress):
        if self.batch is not None and self.batch.previous_entry_id == previous_progress:
            return self.batch
        return None

    async def create_or_load_cognitive_maintenance_batch(self, *, previous_progress, draft):
        if self.batch is None:
            self.batch = CognitiveMaintenanceBatch(
                maintenance_id="frozen-batch",
                user_id="u",
                character_id="luotianyi",
                previous_progress_key=previous_progress or "<origin>",
                previous_entry_id=previous_progress,
                target_entry_id=draft.target_entry_id,
                covered_entry_ids=draft.covered_entry_ids,
                maintained_entry_ids=draft.maintained_entry_ids,
                candidates=draft.candidates,
                proposed_profile=draft.proposed_profile,
                input_digest=draft.input_digest,
                compaction_previous_summary=draft.compaction_previous_summary,
                compaction_covered_entry_ids=draft.compaction_covered_entry_ids,
                compaction_summary=draft.compaction_summary,
                compaction_expected_count=draft.compaction_expected_count,
                created_at=datetime.now(),
            )
        return self.batch

    async def commit_cognitive_maintenance(self, *, compaction, expected_progress, new_progress, maintenance_id=None):
        if not self.cas or self.progress != expected_progress:
            return False
        if compaction is not None:
            self.compactions.append(compaction)
        self.progress = new_progress
        return True


class User:
    def __init__(self, profile="旧画像", *, fail=False):
        self.snapshot = UserContextSnapshot(profile=UserProfile(profile))
        self.fail = fail
        self.updates = []

    def read(self):
        return self.snapshot

    async def update_profile(self, profile):
        if self.fail:
            raise RuntimeError("profile failed")
        self.updates.append(profile)
        self.snapshot = UserContextSnapshot(profile=profile)


class Compaction:
    def __init__(self, *, required=False, keep=2, fail=False):
        self.required = required
        self.keep = keep
        self.fail = fail
        self.model_calls = 0

    def requires_compaction(self, conversation):
        return self.required

    async def compact(self, conversation):
        self.model_calls += 1
        if self.fail:
            raise RuntimeError("compaction failed")
        snapshot = conversation.read()
        covered = snapshot.entries[: -self.keep] if self.keep else snapshot.entries
        return ConversationCompaction(
            snapshot.summary,
            tuple(item.entry_id for item in covered),
            ConversationSummary("新总结"),
        )


class Memory:
    def __init__(self, *, fail_extract=False, fail_write=False, profile="新画像"):
        self.fail_extract = fail_extract
        self.fail_write = fail_write
        self.profile = profile
        self.extracts = []
        self.writes = []
        self.profiles = []
        self.extract_result = (MaintenanceCandidate(MaintenanceMemoryType.USER_FACT, "用户喜欢茶"),)

    async def extract_maintenance_candidates(self, *, history, current_dialogue):
        self.extracts.append((history, current_dialogue))
        if self.fail_extract:
            raise RuntimeError("extract failed")
        return self.extract_result

    async def write_maintenance_candidates(self, *, user_id, maintenance_id, candidates):
        if self.fail_write:
            raise RuntimeError("write failed")
        self.writes.append((user_id, maintenance_id, candidates))

    async def propose_user_profile(self, *, history, current_profile):
        self.profiles.append((history, current_profile))
        return self.profile


def context(entries=(), progress=None, *, cas=True, profile_fail=False):
    return SimpleNamespace(
        conversation=Conversation(entries, progress, cas=cas),
        user=User(fail=profile_fail),
    )


def skill(memory=None, compaction=None):
    return CognitiveMaintenanceSkill(
        memories={"luotianyi": memory or Memory()},
        compaction=compaction or Compaction(),
    )


@pytest.mark.asyncio
async def test_below_threshold_has_zero_model_and_persistent_side_effects():
    memory, compaction = Memory(), Compaction(required=False)
    ctx = context((entry(1),))
    report = await skill(memory, compaction).maintain_if_compaction_needed(invocation(), ctx)

    assert report.status is MaintenanceStatus.SKIPPED
    assert memory.extracts == memory.writes == memory.profiles == []
    assert compaction.model_calls == 0
    assert ctx.conversation.progress is None


@pytest.mark.asyncio
async def test_threshold_maintains_only_covered_prefix_after_marker_then_compacts():
    memory, compaction = Memory(), Compaction(required=True, keep=2)
    ctx = context(tuple(entry(index) for index in range(1, 7)), progress="e2")
    report = await skill(memory, compaction).maintain_if_compaction_needed(invocation(), ctx)

    assert report.maintained_entry_ids == ("e3", "e4")
    assert report.covered_entry_ids == ("e1", "e2", "e3", "e4")
    assert ctx.conversation.progress == "e4"
    assert len(ctx.conversation.compactions) == 1
    assert "消息5" not in memory.extracts[0][1]


@pytest.mark.asyncio
async def test_marker_outside_current_window_treats_window_as_new():
    ctx = context((entry(3), entry(4)), progress="e2")
    report = await skill().maintain(invocation(), ctx, reason=MaintenanceReason.INTERACTION_ENDING)
    assert report.maintained_entry_ids == ("e3", "e4")
    assert ctx.conversation.progress == "e4"


@pytest.mark.asyncio
async def test_ending_maintains_short_dialogue_without_forced_compaction():
    memory, compaction = Memory(), Compaction(required=False)
    ctx = context((entry(1), entry(2)))
    report = await skill(memory, compaction).maintain(invocation(), ctx, reason=MaintenanceReason.INTERACTION_ENDING)
    assert report.status is MaintenanceStatus.COMPLETED
    assert report.compacted is False
    assert compaction.model_calls == 0
    assert ctx.conversation.progress == "e2"


@pytest.mark.asyncio
async def test_ending_with_no_new_entries_has_no_models_or_writes():
    memory = Memory()
    ctx = context((entry(1), entry(2)), progress="e2")
    report = await skill(memory).maintain(invocation(), ctx, reason=MaintenanceReason.INTERACTION_ENDING)
    assert report.status is MaintenanceStatus.SKIPPED
    assert memory.extracts == memory.writes == memory.profiles == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["extract", "write", "profile", "compaction"])
async def test_failure_does_not_advance_progress(failure):
    memory = Memory(fail_extract=failure == "extract", fail_write=failure == "write")
    compaction = Compaction(required=True, keep=1, fail=failure == "compaction")
    ctx = context((entry(1), entry(2)), profile_fail=failure == "profile")
    with pytest.raises(RuntimeError):
        await skill(memory, compaction).maintain_if_compaction_needed(invocation(), ctx)
    assert ctx.conversation.progress is None


@pytest.mark.asyncio
async def test_cas_conflict_does_not_compact_or_overwrite_progress():
    ctx = context((entry(1), entry(2)), cas=False)
    report = await skill(compaction=Compaction(required=True, keep=1)).maintain_if_compaction_needed(invocation(), ctx)
    assert report.status is MaintenanceStatus.CONFLICT
    assert ctx.conversation.progress is None
    assert len(ctx.conversation.compactions) == 0


@pytest.mark.asyncio
async def test_same_batch_uses_stable_maintenance_identity():
    first_memory, second_memory = Memory(), Memory()
    first_context = context((entry(1), entry(2)))
    second_context = context((entry(1), entry(2)))
    await skill(first_memory).maintain(invocation(), first_context, reason=MaintenanceReason.INTERACTION_ENDING)
    await skill(second_memory).maintain(invocation(), second_context, reason=MaintenanceReason.INTERACTION_ENDING)
    assert first_memory.writes[0][1] == second_memory.writes[0][1]


@pytest.mark.asyncio
async def test_retry_uses_frozen_candidates_and_profile_without_model_recall():
    memory, compaction = Memory(), Compaction(required=True, keep=0)
    ctx = context((entry(1), entry(2)), cas=False)
    first = await skill(memory, compaction).maintain_if_compaction_needed(invocation(), ctx)
    assert first.status is MaintenanceStatus.CONFLICT
    assert len(memory.extracts) == len(memory.profiles) == 1
    frozen_candidates = ctx.conversation.batch.candidates
    frozen_profile = ctx.conversation.batch.proposed_profile
    memory.profile = "已改变的画像"
    ctx.conversation.cas = True
    second = await skill(memory, compaction).maintain_if_compaction_needed(invocation(), ctx)
    assert second.status is MaintenanceStatus.COMPLETED
    assert len(memory.extracts) == len(memory.profiles) == 1
    assert memory.writes[-1][2][0].content == frozen_candidates[0]["content"]
    assert ctx.user.read().profile.description == frozen_profile


@pytest.mark.asyncio
async def test_initial_empty_candidate_batch_is_persisted_then_retried_without_models():
    memory = Memory()
    memory.extract_result = ()
    ctx = context((entry(1),), cas=False)
    await skill(memory).maintain(invocation(), ctx, reason=MaintenanceReason.INTERACTION_ENDING)
    assert ctx.conversation.batch.candidates == []
    ctx.conversation.cas = True
    await skill(memory).maintain(invocation(), ctx, reason=MaintenanceReason.INTERACTION_ENDING)
    assert len(memory.extracts) == 1


@pytest.mark.asyncio
async def test_cancellation_before_progress_does_not_advance_marker():
    token_invocation = invocation()
    ctx = context((entry(1),))
    memory = Memory()

    async def cancel_after_write(**kwargs):
        memory.writes.append(kwargs)
        token_invocation.cancellation.cancel(d.CancellationReason.NO_LONGER_NEEDED)

    memory.write_maintenance_candidates = cancel_after_write
    with pytest.raises(asyncio.CancelledError):
        await skill(memory).maintain(token_invocation, ctx, reason=MaintenanceReason.INTERACTION_ENDING)
    assert ctx.conversation.progress is None
