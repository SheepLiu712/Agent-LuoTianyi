"""Call-only summary and maintenance skills over immutable final snapshots."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import replace
from hashlib import sha256
from typing import Protocol

from src.agent.context import UserProfile
from src.agent.skills.contracts import SkillInvocation
from src.domain.agent import MaintenanceCandidate
from src.domain.call import CallFinalSnapshot, CallReplyStatus
from src.domain.call.contracts import CallMaintenanceSnapshot
from src.infrastructure.persistence.call_maintenance import CallMaintenanceBatch
from src.utils.owned_operation import complete_owned

EMPTY_CALL_SUMMARY = "本次通话未形成有效对话内容"
FAILED_CALL_SUMMARY = "本次通话未能形成可用概要"


def render_call_turns(snapshot: CallFinalSnapshot, *, after_turn_seq: int = 0) -> tuple[str, ...]:
    """Keep every completed user fact; include only fully completed formal replies."""
    rendered = []
    for turn in snapshot.completed_turns:
        if turn.turn_seq <= after_turn_seq:
            continue
        text = f"用户：{turn.user_semantic}"
        if turn.reply_status is CallReplyStatus.COMPLETED and turn.formal_agent_text is not None:
            text += f"\n角色：{turn.formal_agent_text}"
        rendered.append(text)
    return tuple(rendered)


class CallSummaryModel(Protocol):
    async def generate_response(self, **kwargs) -> str: ...


class CallSummarySkill:
    def __init__(self, models: dict[str, CallSummaryModel]) -> None:
        self._models = models

    def supports_character(self, character_id: str) -> bool:
        model = self._models.get(character_id)
        return model is not None and callable(getattr(model, "generate_response", None))

    async def summarize(self, invocation: SkillInvocation, snapshot: CallFinalSnapshot) -> str:
        turns = render_call_turns(snapshot)
        if not turns:
            return EMPTY_CALL_SUMMARY
        model = self._models.get(invocation.character_id)
        if model is None:
            return FAILED_CALL_SUMMARY
        for _ in range(2):
            try:
                summary = str(await model.generate_response(completed_turns=turns)).strip()
                if summary and len(summary) <= 200:
                    return summary
            except Exception:
                continue
        return FAILED_CALL_SUMMARY


class CallMaintenanceMemory(Protocol):
    async def extract_maintenance_candidates(
        self, *, history: str, current_dialogue: str
    ) -> tuple[MaintenanceCandidate, ...]: ...

    async def write_maintenance_candidates(
        self, *, user_id: str, maintenance_id: str, candidates: tuple[MaintenanceCandidate, ...]
    ) -> None: ...

    async def propose_user_profile(self, *, history: dict[str, object], current_profile: str) -> str | None: ...


class CallMaintenanceSkill:
    def __init__(self, memories: dict[str, CallMaintenanceMemory], batches=None, *, calls=None) -> None:
        self._memories = memories
        self._batches = batches
        self._calls = calls
        self._pending = {}
        self._progress = {}
        self._locks = {}
        self._local_batches: dict[tuple[object, str, str, int, int], CallMaintenanceBatch] = {}

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
        key = (
            _call_id(snapshot),
            invocation.require_user_id(),
            invocation.character_id,
            snapshot.maintenance_turn_seq,
            turns[-1].turn_seq,
        )
        frozen = self._local_batches.get(key)
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
            self._local_batches[key] = frozen
        await memory.write_maintenance_candidates(
            user_id=invocation.require_user_id(),
            maintenance_id=frozen.maintenance_id,
            candidates=frozen.candidates,
        )
        return turns[-1].turn_seq, frozen.proposed_profile

    async def maintain_window(self, invocation, context, snapshot, *, compaction) -> None:
        """Compact only a settled prefix; retry the same frozen batch once."""
        call_id = snapshot.call_id
        async with self._locks.setdefault(call_id, asyncio.Lock()):
            for attempt in range(2):
                try:
                    await self._maintain_window_once(invocation, context, snapshot, compaction)
                    return
                except Exception:
                    logging.getLogger(__name__).warning(
                        "Call threshold maintenance failed call_id=%s attempt=%s", call_id, attempt + 1
                    )
                    if attempt:
                        raise

    async def _maintain_window_once(self, invocation, context, snapshot, compaction):
        self._check_cancelled(invocation)
        call_id = snapshot.call_id
        pending = self._pending.get(call_id)
        if pending is None:
            if not compaction.requires_compaction(context.conversation):
                return
            window = context.conversation.read()
            result = await compaction.compact(context.conversation)
            if result is None:
                return
            covered = set(result.covered_entry_ids)
            # The seed participates in working-summary compression only. Turn IDs
            # are assigned by the call handler; no seed text enters memory extraction.
            covered_turns = {_entry_turn(entry.entry_id) for entry in window.entries if entry.entry_id in covered}
            covered_turns.discard(None)
            settled = {turn.turn_seq for turn in snapshot.completed_turns}
            if not covered_turns.issubset(settled):
                return
            partial = {_entry_turn(entry.entry_id) for entry in window.entries if entry.entry_id not in covered}
            whole = covered_turns - partial
            progress = await self._read_progress(call_id, snapshot.maintenance_turn_seq)
            # Never advance over an earlier turn split by the compaction boundary.
            boundary = min((seq for seq in partial if seq is not None), default=float("inf"))
            target = max((seq for seq in whole if seq < boundary), default=progress)
            bounded = CallMaintenanceSnapshot(
                call_id,
                tuple(turn for turn in snapshot.completed_turns if turn.turn_seq <= target),
                progress,
            )
            digest = _threshold_digest(bounded)
            pending = (bounded, result, digest)
            self._pending[call_id] = pending
        bounded, result, digest = pending
        await self._apply_pending(invocation, context, bounded, digest)
        self._check_cancelled(invocation)
        await complete_owned(self._commit_window(context, call_id, result))

    async def _commit_window(self, context, call_id, result):
        # Context finishes an owned write before propagating cancellation. Retire
        # its matching transient batch in the same owned boundary.
        await context.conversation.compact(result)
        self._pending.pop(call_id, None)

    async def _read_progress(self, call_id, fallback):
        if self._calls is not None:
            record = await complete_owned(asyncio.to_thread(self._calls.find_by_id, call_id))
            if record is None:
                raise RuntimeError("call maintenance ledger missing")
            return record.maintenance_turn_seq
        return self._progress.get(call_id, fallback)

    async def _apply_pending(self, invocation, context, snapshot, digest):
        previous = snapshot.maintenance_turn_seq
        target = snapshot.completed_turns[-1].turn_seq if snapshot.completed_turns else previous
        if target <= await self._read_progress(snapshot.call_id, previous):
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
        if self._calls is not None:
            changed = await complete_owned(
                asyncio.to_thread(
                    self._calls.advance_maintenance_progress,
                    snapshot.call_id,
                    expected_turn_seq=previous,
                    new_turn_seq=turn_seq,
                )
            )
            if not changed and await self._read_progress(snapshot.call_id, previous) != turn_seq:
                raise RuntimeError("call maintenance progress conflict")
        self._progress[snapshot.call_id] = turn_seq
        if self._batches is not None:
            identity = f"call:{snapshot.call_id}:{previous}:{turn_seq}"
            maintenance_id = "call-maint-v1-" + sha256(identity.encode("utf-8")).hexdigest()
            await complete_owned(asyncio.to_thread(self._batches.mark_completed, maintenance_id))

    async def maintain_ending(self, invocation, context, snapshot, *, settlement_input_digest):
        """Finish an interrupted threshold batch before processing the final tail."""
        call_id = _call_id(snapshot)
        async with self._locks.setdefault(call_id, asyncio.Lock()):
            progress = await self._read_progress(call_id, snapshot.maintenance_turn_seq)
            pending = self._pending.get(call_id)
            if pending is None and self._batches is not None:
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
                    digest = _threshold_digest(bounded)
                    if digest != batch.settlement_input_digest:
                        raise ValueError("SETTLEMENT_INPUT_CONFLICT")
                    pending = (bounded, None, digest)
                    break
            if pending is not None:
                bounded, _, digest = pending
                await self._apply_pending(invocation, context, bounded, digest)
                self._pending.pop(call_id, None)
            progress = await self._read_progress(call_id, snapshot.maintenance_turn_seq)
            bounded = replace(snapshot, maintenance_turn_seq=progress)
            turn_seq, profile = await self.maintain(
                invocation,
                bounded,
                current_profile=context.user.read().profile.description,
                settlement_input_digest=settlement_input_digest,
            )
            self._check_cancelled(invocation)
            if profile is not None:
                await context.user.update_profile(UserProfile(description=profile))
            return turn_seq

    @staticmethod
    def _check_cancelled(invocation):
        if invocation.cancellation.is_cancelled:
            raise asyncio.CancelledError

    def release(self, call_id) -> None:
        self._pending.pop(call_id, None)
        self._progress.pop(call_id, None)
        self._locks.pop(call_id, None)
        for key in tuple(self._local_batches):
            if key[0] == call_id:
                self._local_batches.pop(key, None)


def _call_id(snapshot):
    return snapshot.call_id if isinstance(snapshot, CallMaintenanceSnapshot) else snapshot.terminal.call_id


def _entry_turn(entry_id):
    match = re.fullmatch(r"call-turn-(\d+)-(?:user|agent-\d+)", entry_id)
    return int(match.group(1)) if match else None


def _threshold_digest(snapshot: CallMaintenanceSnapshot) -> str:
    payload = [
        str(snapshot.call_id),
        snapshot.maintenance_turn_seq,
        [
            [turn.turn_seq, turn.user_semantic, turn.reply_status.value, turn.formal_agent_text]
            for turn in snapshot.completed_turns
        ],
    ]
    return sha256(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
