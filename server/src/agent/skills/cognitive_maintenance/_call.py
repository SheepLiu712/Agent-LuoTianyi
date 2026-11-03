"""通话维护的内部实现，保留批次冻结及进度提交规则。"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import replace
from hashlib import sha256
from typing import Protocol

from src.agent.context import UserProfile
from src.agent.skills.cognitive.call_settlement import render_call_turns
from src.agent.skills.contracts import SkillInvocation
from src.domain.agent import MaintenanceCandidate
from src.domain.call import CallFinalSnapshot
from src.domain.call.contracts import CallMaintenanceSnapshot
from src.infrastructure.persistence.call_maintenance import CallMaintenanceBatch
from src.utils.owned_operation import complete_owned


class CallMaintenanceMemory(Protocol):
    async def extract_maintenance_candidates(
        self, *, history: str, current_dialogue: str
    ) -> tuple[MaintenanceCandidate, ...]: ...

    async def write_maintenance_candidates(
        self, *, user_id: str, maintenance_id: str, candidates: tuple[MaintenanceCandidate, ...]
    ) -> None: ...

    async def propose_user_profile(self, *, history: dict[str, object], current_profile: str) -> str | None: ...


class _WorkingConversation:
    def __init__(self, snapshot) -> None:
        self._snapshot = snapshot

    def read(self):
        return self._snapshot


class _CallMaintenance:
    def __init__(self, memories: dict[str, CallMaintenanceMemory], batches=None) -> None:
        self._memories = memories
        self._batches = batches

    async def maintain(
        self,
        invocation: SkillInvocation,
        snapshot: CallFinalSnapshot,
        *,
        current_profile: str,
        settlement_input_digest: str,
    ) -> tuple[int, str | None]:
        turns = tuple(turn for turn in snapshot.completed_turns if turn.turn_seq > snapshot.maintenance_turn_seq)
        lines = render_call_turns(snapshot, after_turn_seq=snapshot.maintenance_turn_seq)
        if not lines:
            return snapshot.maintenance_turn_seq, None
        identity = f"call:{_call_id(snapshot)}:{snapshot.maintenance_turn_seq}:{turns[-1].turn_seq}"
        maintenance_id = "call-maint-v1-" + sha256(identity.encode("utf-8")).hexdigest()
        memory = self._memories[invocation.character_id]
        frozen = None
        if self._batches is not None:
            frozen = await complete_owned(
                asyncio.to_thread(
                    self._batches.load,
                    call_id=_call_id(snapshot),
                    user_id=invocation.require_user_id(),
                    character_id=invocation.character_id,
                    previous_turn_seq=snapshot.maintenance_turn_seq,
                    target_turn_seq=turns[-1].turn_seq,
                )
            )
            if frozen is not None and frozen.settlement_input_digest != settlement_input_digest:
                raise ValueError("SETTLEMENT_INPUT_CONFLICT")
        if frozen is None:
            candidates = await memory.extract_maintenance_candidates(history="", current_dialogue="\n".join(lines))
            profile = await memory.propose_user_profile(
                history={"summary": "", "recent_conversation": list(lines)},
                current_profile=current_profile,
            )
            proposed = CallMaintenanceBatch(
                maintenance_id=maintenance_id,
                call_id=_call_id(snapshot),
                user_id=invocation.require_user_id(),
                character_id=invocation.character_id,
                previous_turn_seq=snapshot.maintenance_turn_seq,
                target_turn_seq=turns[-1].turn_seq,
                settlement_input_digest=settlement_input_digest,
                candidates=candidates,
                proposed_profile=profile,
                status="frozen",
            )
            frozen = (
                await complete_owned(asyncio.to_thread(self._batches.create_or_load, proposed))
                if self._batches is not None
                else proposed
            )
        await memory.write_maintenance_candidates(
            user_id=invocation.require_user_id(),
            maintenance_id=frozen.maintenance_id,
            candidates=frozen.candidates,
        )
        return turns[-1].turn_seq, frozen.proposed_profile

    async def maintain_window(self, invocation, context, snapshot, *, compaction) -> None:
        """Maintain and compact one settled prefix without shared interaction state."""
        for attempt in range(2):
            try:
                await self._maintain_window_once(invocation, context, snapshot, compaction)
                return
            except Exception:
                logging.getLogger(__name__).warning(
                    "Call threshold maintenance failed call_id=%s attempt=%s", snapshot.call_id, attempt + 1
                )
                if attempt:
                    raise

    async def _maintain_window_once(self, invocation, context, snapshot, compaction):
        self._check_cancelled(invocation)
        call_id = snapshot.call_id
        window = context.conversation.read_working()
        bounded = _WorkingConversation(window)
        if not compaction.requires_compaction(bounded):
            return
        planned = compaction.planned_covered_entries(bounded)
        covered = {entry.entry_id for entry in planned}
        covered_turns = {_entry_turn(entry.entry_id) for entry in window.entries if entry.entry_id in covered}
        covered_turns.discard(None)
        settled = {turn.turn_seq for turn in snapshot.completed_turns}
        if not covered_turns.issubset(settled):
            return
        partial = {_entry_turn(entry.entry_id) for entry in window.entries if entry.entry_id not in covered}
        whole = covered_turns - partial
        progress = context.conversation.read_call_maintenance_progress()
        # Never advance over an earlier turn split by the compaction boundary.
        boundary = min((seq for seq in partial if seq is not None), default=float("inf"))
        target = max((seq for seq in whole if seq < boundary), default=progress)
        # A merged reply belongs to the whole batch; never compact half of it.
        crossing = [
            turn.turn_seq
            for turn in snapshot.completed_turns
            if turn.turn_seq <= target and turn.reply_turn_seq is not None and turn.reply_turn_seq > target
        ]
        if crossing:
            target = min(crossing) - 1
        safe_ids = tuple(
            entry.entry_id
            for entry in window.entries
            if (turn_seq := _entry_turn(entry.entry_id)) is not None and turn_seq <= target
        )
        if not safe_ids:
            return
        result = await compaction.compact_prefix(bounded, safe_ids)
        maintenance = CallMaintenanceSnapshot(
            call_id,
            tuple(turn for turn in snapshot.completed_turns if turn.turn_seq <= target),
            progress,
        )
        digest = _maintenance_digest(maintenance)
        await self._apply_pending(invocation, context, maintenance, digest)
        self._check_cancelled(invocation)
        await context.conversation.compact(result)

    @staticmethod
    def _read_progress(context):
        return context.conversation.read_call_maintenance_progress()

    async def _apply_pending(self, invocation, context, snapshot, digest):
        previous = snapshot.maintenance_turn_seq
        target = snapshot.completed_turns[-1].turn_seq if snapshot.completed_turns else previous
        if target <= self._read_progress(context):
            return
        turn_seq, profile = await self.maintain(
            invocation,
            snapshot,
            current_profile=context.user.read().profile.description,
            settlement_input_digest=digest,
        )
        self._check_cancelled(invocation)
        if profile is not None:
            await context.user.update_profile(UserProfile(description=profile))
        self._check_cancelled(invocation)
        if self._batches is not None:
            identity = f"call:{snapshot.call_id}:{previous}:{turn_seq}"
            maintenance_id = "call-maint-v1-" + sha256(identity.encode("utf-8")).hexdigest()
            await complete_owned(asyncio.to_thread(self._batches.mark_completed, maintenance_id))
        if not context.conversation.advance_call_maintenance_progress(expected=previous, new=turn_seq):
            raise RuntimeError("call maintenance progress conflict")

    async def maintain_ending(self, invocation, context, snapshot):
        """Finish an interrupted threshold batch before processing the final tail."""
        call_id = _call_id(snapshot)
        settlement_input_digest = _maintenance_digest(snapshot)
        progress = self._read_progress(context)
        pending = None
        if self._batches is not None:
            batches = await complete_owned(
                asyncio.to_thread(
                    self._batches.list_for_call,
                    call_id=call_id,
                    user_id=invocation.require_user_id(),
                    character_id=invocation.character_id,
                )
            )
            for batch in batches:
                if batch.previous_turn_seq != progress or batch.settlement_input_digest == settlement_input_digest:
                    continue
                bounded = CallMaintenanceSnapshot(
                    call_id,
                    tuple(t for t in snapshot.completed_turns if t.turn_seq <= batch.target_turn_seq),
                    progress,
                )
                digest = _maintenance_digest(bounded)
                if digest != batch.settlement_input_digest:
                    raise ValueError("SETTLEMENT_INPUT_CONFLICT")
                pending = (bounded, None, digest)
                break
        if pending is not None:
            bounded, _, digest = pending
            await self._apply_pending(invocation, context, bounded, digest)
        progress = self._read_progress(context)
        bounded = replace(snapshot, maintenance_turn_seq=progress)
        turn_seq, profile = await self.maintain(
            invocation,
            bounded,
            current_profile=context.user.read().profile.description,
            settlement_input_digest=_maintenance_digest(bounded),
        )
        self._check_cancelled(invocation)
        if profile is not None:
            await context.user.update_profile(UserProfile(description=profile))
        if self._batches is not None and turn_seq > progress:
            identity = f"call:{snapshot.terminal.call_id}:{progress}:{turn_seq}"
            maintenance_id = "call-maint-v1-" + sha256(identity.encode("utf-8")).hexdigest()
            await complete_owned(asyncio.to_thread(self._batches.mark_completed, maintenance_id))
        if not context.conversation.advance_call_maintenance_progress(expected=progress, new=turn_seq):
            raise RuntimeError("call maintenance progress conflict")
        return turn_seq

    @staticmethod
    def _check_cancelled(invocation):
        if invocation.cancellation.is_cancelled:
            raise asyncio.CancelledError


def _call_id(snapshot):
    return snapshot.call_id if isinstance(snapshot, CallMaintenanceSnapshot) else snapshot.terminal.call_id


def _entry_turn(entry_id):
    match = re.fullmatch(r"call-turn-(\d+)-(?:user|agent-[\w-]+)", entry_id)
    return int(match.group(1)) if match else None


def _maintenance_digest(snapshot: CallMaintenanceSnapshot | CallFinalSnapshot) -> str:
    payload = [
        str(_call_id(snapshot)),
        snapshot.maintenance_turn_seq,
        [
            [
                turn.turn_seq,
                turn.user_semantic,
                turn.reply_status.value,
                turn.formal_agent_text,
                turn.reply_turn_seq,
                turn.confirmed_agent_text,
            ]
            for turn in snapshot.completed_turns
        ],
    ]
    return sha256(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
