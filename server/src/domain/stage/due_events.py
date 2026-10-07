"""Stage 读取并原子占用到期提醒的窄端口。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class DueEvent:
    """Stage 做投递决策所需的最小到期事件快照。"""

    event_id: str
    trigger_key: str
    reason: str
    due_at: datetime
    character_id: str
    is_personal: bool
    target_user_id: str | None
    is_notified: bool


class DueEventProvider(Protocol):
    """列出候选并按完整通知身份执行原子 claim/release。"""

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

    def release(
        self,
        event_id: str,
        *,
        user_id: str,
        character_id: str,
        trigger_key: str,
    ) -> None: ...
