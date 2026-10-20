"""Stable, provider-neutral values shared by realtime call components."""

from .content import CALL_CONVERSATION_NAMESPACE, CallContent, derive_call_conversation_id
from .contracts import (
    CallAnswerDecision,
    CallAudioRoute,
    CallFinalSnapshot,
    CallFinalTurn,
    CallReplyStatus,
    CallSpeechDelivery,
    CallTerminalFacts,
)
from .recall import AckStyle, CallRecallDecision, RecallMode
from .settlement import DEFAULT_CALL_SUMMARY, CallEndingResult, CallSummarySource, fallback_call_summary
from .types import CallAudioSemantic, CallEndReason, CallOutcome, CallState

__all__ = [
    "AckStyle",
    "CALL_CONVERSATION_NAMESPACE",
    "CallAudioSemantic",
    "CallAnswerDecision",
    "CallEndingResult",
    "CallSummarySource",
    "DEFAULT_CALL_SUMMARY",
    "CallAudioRoute",
    "CallContent",
    "CallEndReason",
    "CallFinalTurn",
    "CallFinalSnapshot",
    "CallReplyStatus",
    "CallOutcome",
    "CallRecallDecision",
    "CallSpeechDelivery",
    "CallState",
    "CallTerminalFacts",
    "RecallMode",
    "derive_call_conversation_id",
    "fallback_call_summary",
]
