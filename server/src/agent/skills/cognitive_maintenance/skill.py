"""Durably recoverable long-term cognitive maintenance."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from src.agent.context import (
    ConversationCompaction,
    ConversationEntry,
    ConversationSnapshot,
    ConversationSummary,
    UserProfile,
)
from src.agent.skills.contracts import SkillInvocation
from src.domain.agent.maintenance import (
    MaintenanceCandidate,
    MaintenanceMemoryType,
    MaintenanceReason,
    MaintenanceReport,
    MaintenanceStatus,
)
from src.domain.call import CallFinalSnapshot
from src.domain.call.contracts import CallMaintenanceSnapshot
from src.infrastructure.persistence.cognitive_maintenance import (
    CognitiveMaintenanceBatch,
    CognitiveMaintenanceBatchDraft,
)

from ._call import _CallMaintenance
from ._compaction import _ConversationCompaction


class _Conversation(Protocol):
    def read(self): ...

    async def read_maintenance_progress(self) -> str | None: ...

    async def load_cognitive_maintenance_batch(
        self, *, previous_progress: str | None
    ) -> CognitiveMaintenanceBatch | None: ...

    async def create_or_load_cognitive_maintenance_batch(
        self, *, previous_progress: str | None, draft: CognitiveMaintenanceBatchDraft
    ) -> CognitiveMaintenanceBatch: ...

    async def commit_cognitive_maintenance(
        self,
        *,
        compaction: ConversationCompaction | None,
        expected_progress: str | None,
        new_progress: str,
        maintenance_id: str | None = None,
    ) -> bool: ...


class _Context(Protocol):
    conversation: _Conversation
    user: Any


class _Compaction(Protocol):
    def requires_compaction(self, conversation_context: _Conversation) -> bool: ...

    async def compact(self, conversation_context: _Conversation) -> ConversationCompaction | None: ...


class _Memory(Protocol):
    async def extract_maintenance_candidates(
        self, *, history: str, current_dialogue: str
    ) -> tuple[MaintenanceCandidate, ...]: ...

    async def write_maintenance_candidates(
        self, *, user_id: str, maintenance_id: str, candidates: tuple[MaintenanceCandidate, ...]
    ) -> None: ...

    async def propose_user_profile(self, *, history: dict[str, Any], current_profile: str) -> str | None: ...


class _BoundedConversation:
    """Expose one immutable conversation snapshot to a compaction skill."""

    def __init__(self, snapshot: ConversationSnapshot) -> None:
        self._snapshot = snapshot

    def read(self) -> ConversationSnapshot:
        return self._snapshot


@dataclass(frozen=True)
class MaintenanceRequest:
    reason: MaintenanceReason
    context: _Context
    call_snapshot: CallFinalSnapshot | CallMaintenanceSnapshot | None = None
    through_entry_id: str | None = None


MaintenanceResult = MaintenanceReport


class CognitiveMaintenanceSkill:
    """统一选择维护策略；冻结输出后收敛长期记忆、画像与进度。"""

    def __init__(self, config: dict, *, llm_service, memories: Mapping[str, _Memory], batches=None) -> None:
        if not memories:
            raise ValueError("认知维护至少需要一个角色记忆适配器")
        self._memories = dict(memories)
        self._compaction = _ConversationCompaction(config.get("conversation_compaction", {}), llm_service)
        self._call_maintenance = _CallMaintenance(dict(memories), batches)

    async def maintain(self, invocation: SkillInvocation, *, request: MaintenanceRequest) -> MaintenanceResult:
        self._check_cancelled(invocation)
        context, reason = request.context, request.reason
        if request.call_snapshot is not None:
            return await self._maintain_call(invocation, request)
        if reason is MaintenanceReason.COMPACTION_THRESHOLD and not self._compaction.requires_compaction(
            context.conversation
        ):
            return MaintenanceReport(MaintenanceStatus.SKIPPED, reason, None, None)
        return await self._maintain_chat(invocation, context, reason=reason, boundary=request.through_entry_id)

    async def _maintain_call(self, invocation, request):
        context, snapshot, reason = request.context, request.call_snapshot, request.reason
        previous = context.conversation.read_call_maintenance_progress()
        before = context.conversation.read_working()
        profile_before = context.user.read().profile.description
        if reason is MaintenanceReason.COMPACTION_THRESHOLD:
            if not isinstance(snapshot, CallMaintenanceSnapshot):
                raise TypeError("通话阈值维护需要 CallMaintenanceSnapshot")
            await self._call_maintenance.maintain_window(invocation, context, snapshot, compaction=self._compaction)
        else:
            if not isinstance(snapshot, CallFinalSnapshot):
                raise TypeError("通话结束维护需要 CallFinalSnapshot")
            await self._call_maintenance.maintain_ending(invocation, context, snapshot)
        progress = context.conversation.read_call_maintenance_progress()
        after_ids = {entry.entry_id for entry in context.conversation.read_working().entries}
        covered = tuple(entry.entry_id for entry in before.entries if entry.entry_id not in after_ids)
        return MaintenanceReport(
            MaintenanceStatus.COMPLETED if progress > previous or covered else MaintenanceStatus.SKIPPED,
            reason,
            previous,
            progress,
            covered_entry_ids=covered,
            maintained_entry_ids=tuple(
                f"call-turn-{turn.turn_seq}-user"
                for turn in snapshot.completed_turns
                if previous < turn.turn_seq <= progress
            ),
            profile_updated=profile_before != context.user.read().profile.description,
            compacted=bool(covered),
        )

    async def _maintain_chat(
        self, invocation: SkillInvocation, context: _Context, *, reason: MaintenanceReason, boundary: str | None
    ) -> MaintenanceReport:
        """模型调用不占用生命周期锁，持久化前驱决定批次胜者。"""
        initial_snapshot = context.conversation.read()
        ending_boundary = boundary or (initial_snapshot.entries[-1].entry_id if initial_snapshot.entries else None)
        memory = self._memory_for(invocation.character_id)
        reports = []
        while True:
            report = await self._maintain_batch(
                invocation,
                context,
                reason=reason,
                memory=memory,
                ending_boundary=ending_boundary,
                bounded=boundary is not None or reason is MaintenanceReason.INTERACTION_ENDING,
            )
            reports.append(report)
            if reason is not MaintenanceReason.INTERACTION_ENDING:
                return report
            if report.status is not MaintenanceStatus.COMPLETED:
                return report
            if report.new_progress == ending_boundary:
                return self._combine_reports(reports, reason)
            self._check_cancelled(invocation)

    async def _maintain_batch(
        self, invocation, context, *, reason, memory, ending_boundary, bounded
    ) -> MaintenanceReport:
        current_snapshot = context.conversation.read()
        previous = await context.conversation.read_maintenance_progress()
        entries = self._entries_through_boundary(current_snapshot.entries, ending_boundary, bounded=bounded)
        if entries is None:
            if previous == ending_boundary:
                return MaintenanceReport(MaintenanceStatus.COMPLETED, reason, previous, previous)
            return MaintenanceReport(MaintenanceStatus.CONFLICT, reason, previous, None)
        snapshot = ConversationSnapshot(current_snapshot.summary, entries)
        if bounded and not entries:
            return MaintenanceReport(MaintenanceStatus.SKIPPED, reason, previous, previous)
        batch = await context.conversation.load_cognitive_maintenance_batch(previous_progress=previous)

        if batch is None:
            compaction = await self._prepare_compaction(_BoundedConversation(snapshot), reason)
            covered = self._covered_entries(entries, compaction, reason)
            maintained = self._entries_after_progress(entries, previous)
            if compaction is not None:
                covered_ids = {item.entry_id for item in covered}
                maintained = tuple(item for item in maintained if item.entry_id in covered_ids)
            if not maintained:
                if compaction is not None:
                    committed = await context.conversation.commit_cognitive_maintenance(
                        compaction=compaction,
                        expected_progress=previous,
                        new_progress=previous,
                    )
                    return MaintenanceReport(
                        MaintenanceStatus.COMPLETED if committed else MaintenanceStatus.CONFLICT,
                        reason,
                        previous,
                        previous if committed else None,
                        covered_entry_ids=tuple(item.entry_id for item in covered),
                        compacted=committed,
                    )
                return MaintenanceReport(
                    MaintenanceStatus.SKIPPED,
                    reason,
                    previous,
                    previous,
                    covered_entry_ids=tuple(item.entry_id for item in covered),
                )
            candidates = await memory.extract_maintenance_candidates(
                history=snapshot.summary.text, current_dialogue=self._render_entries(maintained)
            )
            self._check_cancelled(invocation)
            proposed = await memory.propose_user_profile(
                history={"summary": snapshot.summary.text, "recent_conversation": self._render_entry_lines(maintained)},
                current_profile=context.user.read().profile.description,
            )
            draft = CognitiveMaintenanceBatchDraft(
                target_entry_id=maintained[-1].entry_id,
                covered_entry_ids=tuple(item.entry_id for item in covered),
                maintained_entry_ids=tuple(item.entry_id for item in maintained),
                candidates=self._serialize_candidates(candidates),
                proposed_profile=self._normalize_profile(proposed),
                input_digest=self._input_digest(snapshot.summary.text, maintained),
                compaction_previous_summary=compaction.previous_summary.text if compaction else None,
                compaction_covered_entry_ids=compaction.covered_entry_ids if compaction else (),
                compaction_summary=compaction.summary.text if compaction else None,
                compaction_expected_count=len(snapshot.entries) if compaction else None,
            )
            batch = await context.conversation.create_or_load_cognitive_maintenance_batch(
                previous_progress=previous, draft=draft
            )

        # A concurrent winner may differ from the local model output. Only its frozen payload is usable.
        candidates = self._deserialize_candidates(batch.candidates)
        await memory.write_maintenance_candidates(
            user_id=invocation.require_user_id(), maintenance_id=batch.maintenance_id, candidates=candidates
        )
        self._check_cancelled(invocation)
        profile_updated = await self._apply_frozen_profile(context, batch.proposed_profile)
        self._check_cancelled(invocation)
        committed = await context.conversation.commit_cognitive_maintenance(
            compaction=self._compaction_from_batch(batch),
            expected_progress=previous,
            new_progress=batch.target_entry_id,
            maintenance_id=batch.maintenance_id,
        )
        if not committed:
            return MaintenanceReport(
                MaintenanceStatus.CONFLICT,
                reason,
                previous,
                None,
                covered_entry_ids=batch.covered_entry_ids,
                maintained_entry_ids=batch.maintained_entry_ids,
                memory_candidate_count=len(candidates),
                profile_updated=profile_updated,
            )
        return MaintenanceReport(
            MaintenanceStatus.COMPLETED,
            reason,
            previous,
            batch.target_entry_id,
            covered_entry_ids=batch.covered_entry_ids,
            maintained_entry_ids=batch.maintained_entry_ids,
            memory_candidate_count=len(candidates),
            profile_updated=profile_updated,
            compacted=batch.compaction_expected_count is not None,
        )

    @staticmethod
    def _combine_reports(reports, reason):
        if len(reports) == 1:
            return reports[0]
        return MaintenanceReport(
            MaintenanceStatus.COMPLETED,
            reason,
            reports[0].previous_progress,
            reports[-1].new_progress,
            covered_entry_ids=tuple(entry_id for report in reports for entry_id in report.covered_entry_ids),
            maintained_entry_ids=tuple(entry_id for report in reports for entry_id in report.maintained_entry_ids),
            memory_candidate_count=sum(report.memory_candidate_count for report in reports),
            profile_updated=any(report.profile_updated for report in reports),
            compacted=any(report.compacted for report in reports),
        )

    async def _prepare_compaction(
        self, conversation: _Conversation, reason: MaintenanceReason
    ) -> ConversationCompaction | None:
        if reason is MaintenanceReason.COMPACTION_THRESHOLD or self._compaction.requires_compaction(conversation):
            return await self._compaction.compact(conversation)
        return None

    @staticmethod
    def _covered_entries(entries, compaction, reason):
        if compaction is None:
            return entries if reason is MaintenanceReason.INTERACTION_ENDING else ()
        prefix = entries[: len(compaction.covered_entry_ids)]
        if tuple(entry.entry_id for entry in prefix) != compaction.covered_entry_ids:
            raise ValueError("压缩结果不是当前对话的连续前缀")
        return prefix

    @staticmethod
    def _entries_after_progress(entries, progress):
        if progress is None:
            return entries
        for index, entry in enumerate(entries):
            if entry.entry_id == progress:
                return entries[index + 1 :]
        return entries

    @staticmethod
    def _entries_through_boundary(entries, boundary, *, bounded):
        if not bounded:
            return entries
        if boundary is None:
            return ()
        for index, entry in enumerate(entries):
            if entry.entry_id == boundary:
                return entries[: index + 1]
        return None

    @staticmethod
    def _serialize_candidates(candidates):
        return [{"memory_type": item.memory_type.value, "content": item.content} for item in candidates]

    @staticmethod
    def _deserialize_candidates(payload: Any) -> tuple[MaintenanceCandidate, ...]:
        if not isinstance(payload, list):
            raise ValueError("冻结维护候选格式无效")
        return tuple(
            MaintenanceCandidate(MaintenanceMemoryType(item["memory_type"]), item["content"]) for item in payload
        )

    @staticmethod
    def _normalize_profile(profile: str | None) -> str | None:
        value = (profile or "").strip()
        return value or None

    async def _apply_frozen_profile(self, context: _Context, proposed: str | None) -> bool:
        if not proposed or context.user.read().profile.description.strip() == proposed:
            return False
        await context.user.update_profile(UserProfile(proposed))
        return True

    @staticmethod
    def _compaction_from_batch(batch: CognitiveMaintenanceBatch) -> ConversationCompaction | None:
        if batch.compaction_expected_count is None:
            return None
        return ConversationCompaction(
            previous_summary=ConversationSummary(batch.compaction_previous_summary or ""),
            covered_entry_ids=batch.compaction_covered_entry_ids,
            summary=ConversationSummary(batch.compaction_summary or ""),
        )

    @staticmethod
    def _input_digest(summary: str, entries: tuple[ConversationEntry, ...]) -> str:
        value = "\x1f".join(
            [summary, *(f"{item.entry_id}\x1e{item.source}\x1e{item.content.text}" for item in entries)]
        )
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _render_entry_lines(entries):
        return [f"{entry.source}: {entry.content.text}" for entry in entries]

    @classmethod
    def _render_entries(cls, entries):
        return "\n".join(cls._render_entry_lines(entries))

    def _memory_for(self, character_id: str) -> _Memory:
        try:
            return self._memories[character_id]
        except KeyError as error:
            raise KeyError(f"角色 {character_id} 未配置记忆") from error

    @staticmethod
    def _check_cancelled(invocation: SkillInvocation) -> None:
        if invocation.cancellation.is_cancelled:
            raise asyncio.CancelledError
