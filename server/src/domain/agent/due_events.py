"""角色读取当天话题素材并记录分享结果的端口。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class DueEvent:
    """角色选择话题所需的最小事件快照。"""

    event_id: str
    trigger_key: str
    reason: str
    due_at: datetime
    character_id: str
    is_personal: bool
    target_user_id: str | None
    is_notified: bool
    title: str
    description: str


class DueEventProvider(Protocol):
    """列出当天候选，并按用户、角色和触发标识记录已分享。"""

    def list_due(
        self,
        *,
        character_id: str,
        user_id: str,
        now: datetime,
    ) -> tuple[DueEvent, ...]: ...

    def claim(
        self,
        event_id: str,
        *,
        user_id: str,
        character_id: str,
        trigger_key: str,
    ) -> bool: ...
