"""Pure lifecycle state machine for a call session."""

from __future__ import annotations

from dataclasses import dataclass

from src.domain.call import CallEndReason, CallOutcome, CallState


class InvalidCallTransition(ValueError):
    pass


_ALLOWED_TRANSITIONS: dict[CallState, frozenset[CallState]] = {
    CallState.PREPARING: frozenset({CallState.RINGING, CallState.ENDING, CallState.FAILED}),
    CallState.RINGING: frozenset({CallState.ACTIVE, CallState.DECLINED, CallState.ENDING, CallState.FAILED}),
    CallState.ACTIVE: frozenset({CallState.RECONNECTING, CallState.ENDING}),
    CallState.RECONNECTING: frozenset({CallState.ACTIVE, CallState.ENDING}),
    CallState.ENDING: frozenset({CallState.ENDED}),
    CallState.DECLINED: frozenset({CallState.ENDED}),
    CallState.ENDED: frozenset(),
    CallState.FAILED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class CallLifecycleSnapshot:
    state: CallState
    has_connected: bool = False
    outcome: CallOutcome | None = None
    end_reason: CallEndReason | None = None


class CallLifecycle:
    def __init__(self) -> None:
        self._snapshot = CallLifecycleSnapshot(state=CallState.PREPARING)

    @property
    def snapshot(self) -> CallLifecycleSnapshot:
        return self._snapshot

    def transition(
        self,
        state: CallState,
        *,
        outcome: CallOutcome | None = None,
        end_reason: CallEndReason | None = None,
    ) -> CallLifecycleSnapshot:
        if state is self._snapshot.state:
            if outcome == self._snapshot.outcome and end_reason == self._snapshot.end_reason:
                return self._snapshot
            raise InvalidCallTransition("an idempotent transition cannot change terminal facts")
        if state not in _ALLOWED_TRANSITIONS[self._snapshot.state]:
            raise InvalidCallTransition(f"cannot transition from {self._snapshot.state.value} to {state.value}")
        has_connected = self._snapshot.has_connected or state is CallState.ACTIVE
        self._validate_facts(state, has_connected, outcome, end_reason)
        self._snapshot = CallLifecycleSnapshot(
            state=state,
            has_connected=has_connected,
            outcome=outcome,
            end_reason=end_reason,
        )
        return self._snapshot

    @staticmethod
    def _validate_facts(
        state: CallState,
        has_connected: bool,
        outcome: CallOutcome | None,
        end_reason: CallEndReason | None,
    ) -> None:
        if state is CallState.DECLINED:
            if outcome is not CallOutcome.DECLINED or end_reason is not CallEndReason.DECLINED:
                raise InvalidCallTransition("DECLINED requires its matching outcome and reason")
        elif state in {CallState.ENDED, CallState.FAILED}:
            if end_reason is None:
                raise InvalidCallTransition(f"{state.value} requires an end reason")
            if state is CallState.ENDED and outcome is None:
                raise InvalidCallTransition("ended calls require an outcome")
            if state is CallState.FAILED and outcome is not None:
                raise InvalidCallTransition("failed calls cannot have a recordable outcome")
            CallLifecycle._validate_outcome_history(has_connected, outcome)
        elif outcome is not None or end_reason is not None:
            raise InvalidCallTransition("non-result states cannot carry outcome or end reason")

    @staticmethod
    def _validate_outcome_history(has_connected: bool, outcome: CallOutcome | None) -> None:
        if outcome is CallOutcome.CONNECTED and not has_connected:
            raise InvalidCallTransition("CONNECTED requires a prior ACTIVE state")
        if has_connected and outcome in {CallOutcome.CANCELLED_BEFORE_ANSWER, CallOutcome.DECLINED}:
            raise InvalidCallTransition("a connected call cannot use a pre-answer outcome")
