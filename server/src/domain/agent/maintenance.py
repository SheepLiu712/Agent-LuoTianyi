"""认知维护技能的领域值，不接入现有 ActionPlan 公共导出。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MaintenanceReason(str, Enum):
    COMPACTION_THRESHOLD = "compaction_threshold"
    INTERACTION_ENDING = "interaction_ending"


class MaintenanceStatus(str, Enum):
    SKIPPED = "skipped"
    COMPLETED = "completed"
    CONFLICT = "conflict"


class MaintenanceMemoryType(str, Enum):
    USER_FACT = "user_fact"
    INTERACTION_EVENT = "interaction_event"


@dataclass(frozen=True, slots=True)
class MaintenanceCandidate:
    memory_type: MaintenanceMemoryType
    content: str

    def __post_init__(self) -> None:
        content = self.content.strip()
        if not content:
            raise ValueError("认知维护候选内容不能为空")
        object.__setattr__(self, "content", content)


@dataclass(frozen=True, slots=True)
class MaintenanceReport:
    status: MaintenanceStatus
    reason: MaintenanceReason
    previous_progress: str | None
    new_progress: str | None
    covered_entry_ids: tuple[str, ...] = ()
    maintained_entry_ids: tuple[str, ...] = ()
    memory_candidate_count: int = 0
    profile_updated: bool = False
    compacted: bool = False
