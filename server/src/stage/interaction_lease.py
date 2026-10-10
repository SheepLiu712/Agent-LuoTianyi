"""Process-local atomic ownership and one-shot chat-to-call intents."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum


class InteractionSource(str, Enum):
    CHAT = "chat"
    CALL = "call"
    CALL_TRANSITION = "call_transition"


@dataclass(frozen=True, slots=True)
class InteractionLease:
    user_id: str
    character_id: str
    interaction_id: str
    source: InteractionSource


@dataclass(frozen=True, slots=True)
class CallTransitionIntent:
    user_id: str
    character_id: str
    source_interaction_id: str
    client_request_id: str
    expires_at: float


@dataclass(frozen=True, slots=True)
class CallTransitionOwnership:
    intent: CallTransitionIntent
    lease: InteractionLease


class InteractionLeaseRegistry:
    """Single-process ownership registry; distributed coordination is out of scope."""

    def __init__(self, *, monotonic: Callable[[], float] = time.monotonic, intent_ttl_seconds: float = 10.0) -> None:
        if intent_ttl_seconds <= 0:
            raise ValueError("intent_ttl_seconds must be positive")
        self._monotonic = monotonic
        self._intent_ttl_seconds = intent_ttl_seconds
        self._lock = threading.Lock()
        self._leases: dict[tuple[str, str], InteractionLease] = {}
        self._intents: dict[tuple[str, str], CallTransitionIntent] = {}

    def claim(self, lease: InteractionLease) -> bool:
        key = (lease.user_id, lease.character_id)
        with self._lock:
            current = self._leases.get(key)
            if current is not None:
                return current == lease
            self._leases[key] = lease
            return True

    def release(self, lease: InteractionLease) -> bool:
        key = (lease.user_id, lease.character_id)
        with self._lock:
            if self._leases.get(key) != lease:
                return False
            del self._leases[key]
            self._intents.pop(key, None)
            return True

    def prepare_call_transition(self, *, lease: InteractionLease, client_request_id: str) -> CallTransitionIntent:
        if lease.source is not InteractionSource.CHAT:
            raise ValueError("only a chat interaction can prepare a call transition")
        if not client_request_id:
            raise ValueError("client_request_id is required")
        key = (lease.user_id, lease.character_id)
        with self._lock:
            if self._leases.get(key) != lease:
                raise ValueError("the source interaction does not own the lease")
            current = self._live_intent(key)
            if current is not None:
                if (
                    current.source_interaction_id == lease.interaction_id
                    and current.client_request_id == client_request_id
                ):
                    return current
                raise ValueError("a call transition intent already exists")
            intent = CallTransitionIntent(
                user_id=lease.user_id,
                character_id=lease.character_id,
                source_interaction_id=lease.interaction_id,
                client_request_id=client_request_id,
                expires_at=self._monotonic() + self._intent_ttl_seconds,
            )
            self._intents[key] = intent
            return intent

    def consume_call_transition(
        self,
        *,
        user_id: str,
        character_id: str,
        source_interaction_id: str,
        client_request_id: str,
    ) -> CallTransitionIntent | None:
        key = (user_id, character_id)
        with self._lock:
            intent = self._live_intent(key)
            if intent is None:
                return None
            if intent.source_interaction_id != source_interaction_id or intent.client_request_id != client_request_id:
                return None
            del self._intents[key]
            return intent

    def begin_call_transition(
        self,
        *,
        user_id: str,
        character_id: str,
        source_interaction_id: str,
        client_request_id: str,
    ) -> CallTransitionOwnership | None:
        """Consume one intent and atomically replace CHAT ownership with transition ownership."""
        key = (user_id, character_id)
        with self._lock:
            intent = self._live_intent(key)
            current = self._leases.get(key)
            if (
                intent is None
                or current is None
                or current.source is not InteractionSource.CHAT
                or current.interaction_id != source_interaction_id
                or intent.source_interaction_id != source_interaction_id
                or intent.client_request_id != client_request_id
            ):
                return None
            del self._intents[key]
            transition = InteractionLease(
                user_id=user_id,
                character_id=character_id,
                interaction_id=source_interaction_id,
                source=InteractionSource.CALL_TRANSITION,
            )
            self._leases[key] = transition
            return CallTransitionOwnership(intent=intent, lease=transition)

    def begin_direct_call_transition(
        self,
        *,
        user_id: str,
        character_id: str,
        client_request_id: str,
    ) -> InteractionLease | None:
        """Claim transition ownership only when no chat, call, or transition owns the key."""
        if not client_request_id:
            raise ValueError("client_request_id is required")
        key = (user_id, character_id)
        with self._lock:
            self._live_intent(key)
            if self._leases.get(key) is not None:
                return None
            transition = InteractionLease(
                user_id=user_id,
                character_id=character_id,
                interaction_id=client_request_id,
                source=InteractionSource.CALL_TRANSITION,
            )
            self._leases[key] = transition
            return transition

    def finish_call_transition(self, ownership: CallTransitionOwnership, *, call_id: str) -> InteractionLease:
        """Atomically hand transition ownership to a stable call identity."""
        if not call_id:
            raise ValueError("call_id is required")
        key = (ownership.lease.user_id, ownership.lease.character_id)
        with self._lock:
            if self._leases.get(key) != ownership.lease:
                raise ValueError("call transition no longer owns the interaction")
            call_lease = InteractionLease(
                user_id=key[0],
                character_id=key[1],
                interaction_id=call_id,
                source=InteractionSource.CALL,
            )
            self._leases[key] = call_lease
            return call_lease

    def finish_direct_call_transition(self, transition: InteractionLease, *, call_id: str) -> InteractionLease:
        """Finish an empty-slot direct transition without a chat intent."""
        if transition.source is not InteractionSource.CALL_TRANSITION or not call_id:
            raise ValueError("valid direct transition and call_id are required")
        key = (transition.user_id, transition.character_id)
        with self._lock:
            if self._leases.get(key) != transition:
                raise ValueError("direct call transition no longer owns the interaction")
            call = InteractionLease(key[0], key[1], call_id, InteractionSource.CALL)
            self._leases[key] = call
            return call

    def abandon_call_transition(self, ownership: CallTransitionOwnership) -> bool:
        """Release transition ownership after an irreversible handoff failure."""
        return self.release(ownership.lease)

    def rollback_call_transition(self, ownership: CallTransitionOwnership) -> InteractionLease:
        """Restore CHAT ownership after failure before any durable call ledger exists."""
        key = (ownership.lease.user_id, ownership.lease.character_id)
        with self._lock:
            if self._leases.get(key) != ownership.lease:
                raise ValueError("call transition no longer owns the interaction")
            chat = InteractionLease(
                user_id=key[0],
                character_id=key[1],
                interaction_id=ownership.intent.source_interaction_id,
                source=InteractionSource.CHAT,
            )
            self._leases[key] = chat
            self._intents.pop(key, None)
            return chat

    def current(self, user_id: str, character_id: str) -> InteractionLease | None:
        with self._lock:
            return self._leases.get((user_id, character_id))

    def close(self) -> None:
        """Release all process-local ownership and pending intents at runtime shutdown."""
        with self._lock:
            self._leases.clear()
            self._intents.clear()

    def _live_intent(self, key: tuple[str, str]) -> CallTransitionIntent | None:
        intent = self._intents.get(key)
        if intent is not None and self._monotonic() >= intent.expires_at:
            del self._intents[key]
            return None
        return intent
