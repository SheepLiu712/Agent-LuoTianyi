from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class WorldTaskResult:
    task_name: str
    ok: bool
    skipped: bool = False
    message: str = ""
    data: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def success(cls, task_name: str, message: str = "", **data: Any) -> "WorldTaskResult":
        return cls(task_name=task_name, ok=True, message=message, data=data)

    @classmethod
    def skipped_result(cls, task_name: str, message: str = "", **data: Any) -> "WorldTaskResult":
        return cls(task_name=task_name, ok=True, skipped=True, message=message, data=data)

    @classmethod
    def failure(cls, task_name: str, message: str = "", **data: Any) -> "WorldTaskResult":
        return cls(task_name=task_name, ok=False, message=message, data=data)
