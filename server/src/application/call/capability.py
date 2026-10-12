"""Read-only projection of the runtime's public call readiness facts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class CallCapabilityStatusPort(Protocol):
    enabled: bool
    trusted_host: bool
    provider_ready: bool
    call_tts_ready: bool
    summary_ready: bool
    settlement_ready: bool
    stage_binding_ready: bool
    recovery_ready: bool


class CallCapabilityRuntimePort(Protocol):
    call_capability_status: CallCapabilityStatusPort

    def supports_call_character(self, character_id: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class CallCapabilityView:
    available: bool
    character_id: str
    reason: str


def get_call_capability(runtime: CallCapabilityRuntimePort, character_id: str) -> CallCapabilityView:
    """Project readiness in a stable order without exposing runtime internals."""
    status = getattr(runtime, "call_capability_status", None)
    if status is None:
        return CallCapabilityView(False, character_id, "runtime_not_ready")

    checks = (
        ("enabled", "disabled"),
        ("trusted_host", "untrusted_host"),
        ("provider_ready", "provider_unavailable"),
        ("call_tts_ready", "call_tts_unavailable"),
        ("summary_ready", "summary_unavailable"),
        ("settlement_ready", "settlement_unavailable"),
        ("stage_binding_ready", "stage_binding_unavailable"),
        ("recovery_ready", "recovery_unavailable"),
    )
    for field, reason in checks:
        if not getattr(status, field, False):
            return CallCapabilityView(False, character_id, reason)

    supports_character = getattr(runtime, "supports_call_character", None)
    if not callable(supports_character) or not supports_character(character_id):
        return CallCapabilityView(False, character_id, "character_unavailable")
    return CallCapabilityView(True, character_id, "available")
