"""Persistence contracts for a frozen cognitive-maintenance attempt.

These values deliberately live below the domain layer: they describe durable
recovery input, rather than an Agent action or a shared business value.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

ORIGIN_PROGRESS_KEY = "<origin>"


@dataclass(frozen=True)
class CognitiveMaintenanceBatchDraft:
    """The complete model input frozen before an attempt can write projections."""

    target_entry_id: str
    covered_entry_ids: tuple[str, ...]
    maintained_entry_ids: tuple[str, ...]
    candidates: Any
    proposed_profile: str | None
    input_digest: str
    compaction_previous_summary: str | None = None
    compaction_covered_entry_ids: tuple[str, ...] = ()
    compaction_summary: str | None = None
    compaction_expected_count: int | None = None


@dataclass(frozen=True)
class CognitiveMaintenanceBatch:
    """An immutable, persisted cognitive-maintenance attempt."""

    maintenance_id: str
    user_id: str
    character_id: str
    previous_progress_key: str
    previous_entry_id: str | None
    target_entry_id: str
    covered_entry_ids: tuple[str, ...]
    maintained_entry_ids: tuple[str, ...]
    candidates: Any
    proposed_profile: str | None
    input_digest: str
    compaction_previous_summary: str | None
    compaction_covered_entry_ids: tuple[str, ...]
    compaction_summary: str | None
    compaction_expected_count: int | None
    created_at: datetime
