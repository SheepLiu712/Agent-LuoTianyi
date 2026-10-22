"""Input facts survive reply cancellation; attempts reserve an explicit batch."""

from __future__ import annotations

from dataclasses import dataclass

import src.domain.agent as d


@dataclass(slots=True)
class ReplyAttempt:
    request_id: str
    inputs: tuple[d.CallTurnCompleted, ...]
    report: d.HandlingReport | None = None
    interrupted: bool = False

    @property
    def anchor(self) -> int:
        return self.inputs[-1].turn_seq


class CallInputs:
    def __init__(self) -> None:
        self.pending: dict[int, d.CallTurnCompleted] = {}
        self.ready: set[int] = set()
        self.attempt: ReplyAttempt | None = None
        self.speech: set[str | None] = set()
        self.completed_items: set[str] = set()
        self.blocked = False
        self.interrupted = False

    def accept(self, stimulus: d.CallTurnCompleted) -> None:
        self.pending[stimulus.turn_seq] = stimulus
        self.blocked = False

    def can_reply(self) -> bool:
        return (
            bool(self.pending)
            and self.ready.issuperset(self.pending)
            and not self.speech
            and self.attempt is None
            and not self.blocked
        )

    def begin(self, request_id: str) -> ReplyAttempt:
        if not self.can_reply():
            raise RuntimeError("call inputs are not ready for a reply")
        self.attempt = ReplyAttempt(request_id, tuple(self.pending.values()))
        return self.attempt

    def interrupt(self) -> None:
        if self.attempt is not None:
            self.attempt.interrupted = True
            self.attempt = None
            self.interrupted = True

    def settle(self, attempt: ReplyAttempt, *, success: bool) -> tuple[int, ...]:
        if attempt is not self.attempt or attempt.interrupted:
            return ()
        consumed = set(attempt.report.consumed_pending_stimulus_ids) if success and attempt.report else set()
        settled = tuple(item.turn_seq for item in attempt.inputs if item.stimulus_id in consumed)
        for seq in settled:
            self.pending.pop(seq, None)
            self.ready.discard(seq)
        self.attempt = None
        # A failed/no-progress attempt must not busy-loop on the same pending batch.
        self.blocked = not success or not settled
        if success:
            self.interrupted = False
        return settled

    def close(self) -> None:
        self.pending.clear()
        self.ready.clear()
        self.speech.clear()
        self.completed_items.clear()
        self.attempt = None
