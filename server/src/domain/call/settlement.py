"""Settlement identity and Agent-produced results for immutable call snapshots."""

import json
from dataclasses import dataclass
from datetime import timedelta, timezone
from hashlib import sha256

from .contracts import CallFinalSnapshot


@dataclass(frozen=True, slots=True)
class CallAgentSettlementResult:
    summary: str | BaseException
    maintenance_turn_seq: int | BaseException


def call_settlement_input_digest(snapshot: CallFinalSnapshot) -> str:
    """Hash the canonical immutable settlement input without persisting its plaintext."""
    terminal = snapshot.terminal
    payload = {
        "version": 1,
        "call_id": str(terminal.call_id),
        "outcome": terminal.outcome.value,
        "end_reason": terminal.end_reason.value,
        "active_duration_ms": terminal.active_duration_ms,
        "ended_at": terminal.ended_at.astimezone(timezone(timedelta(hours=8))).isoformat(),
        "maintenance_turn_seq": snapshot.maintenance_turn_seq,
        "turns": [
            {
                "turn_seq": turn.turn_seq,
                "user_semantic": turn.user_semantic,
                "reply_status": turn.reply_status.value,
                "formal_agent_text": turn.formal_agent_text,
            }
            for turn in snapshot.completed_turns
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()
