"""Strict validation for the stable call Conversation projection."""

from __future__ import annotations

from src.domain.call import CallContent, CallOutcome, derive_call_conversation_id


def validate_call_conversation_winner(record, item) -> str | None:
    """Return a valid persisted summary or reject an identity/content conflict."""
    if item is None:
        return None
    data = item.data or {}
    conversation_id = derive_call_conversation_id(
        user_id=record.user_id,
        character_id=record.character_id,
        call_id=record.call_id,
    )
    expected = {
        "call_id": str(record.call_id),
        "outcome": record.outcome.value,
        "active_duration_ms": record.active_duration_ms,
        "end_reason": record.end_reason.value,
    }
    summary = data.get("summary")
    try:
        content = CallContent(
            call_id=record.call_id,
            outcome=record.outcome,
            active_duration_ms=record.active_duration_ms,
            summary=summary,
            end_reason=record.end_reason,
        )
    except ValueError as error:
        raise RuntimeError("persisted call conversation content is invalid") from error
    requested_at = record.requested_at.replace(tzinfo=None).isoformat(sep=" ", timespec="microseconds")
    if (
        item.uuid != str(conversation_id)
        or item.source != "user"
        or item.type != "call"
        or item.timestamp != requested_at
        or item.content != content.render_for_agent()
        or set(data) != {"call_id", "outcome", "active_duration_ms", "summary", "end_reason"}
        or any(data.get(key) != value for key, value in expected.items())
    ):
        raise RuntimeError("persisted call conversation identity conflicts with ledger")
    if record.outcome is CallOutcome.CONNECTED and (not isinstance(summary, str) or not summary.strip()):
        raise RuntimeError("persisted connected call has no summary")
    return summary if isinstance(summary, str) else ""
