"""Call-only summary and maintenance skills over immutable final snapshots."""

from __future__ import annotations

import asyncio
from hashlib import sha256
from typing import Protocol

from src.agent.skills.contracts import SkillInvocation
from src.domain.agent import MaintenanceCandidate
from src.domain.call import CallFinalSnapshot, CallReplyStatus
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
    def __init__(self, memories: dict[str, CallMaintenanceMemory], batches=None) -> None:
        self._memories = memories
        self._batches = batches
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
        identity = f"call:{snapshot.terminal.call_id}:{snapshot.maintenance_turn_seq}:{turns[-1].turn_seq}"
        maintenance_id = "call-maint-v1-" + sha256(identity.encode("utf-8")).hexdigest()
        memory = self._memories[invocation.character_id]
        key = (
            snapshot.terminal.call_id,
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
                    call_id=snapshot.terminal.call_id,
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
                call_id=snapshot.terminal.call_id,
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

    def release(self, call_id) -> None:
        for key in tuple(self._local_batches):
            if key[0] == call_id:
                self._local_batches.pop(key, None)
