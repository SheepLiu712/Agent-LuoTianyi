from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping
from uuid import uuid4


class ActionType(str, Enum):
    SAY = "say"
    SING = "sing"
    CHANGE_EXPRESSION = "change_expression"
    LIVE2D_MOTION = "live2d_motion"
    WRITE_MEMORY = "write_memory"
    WRITE_DIARY = "write_diary"
    ASK_FOLLOWUP = "ask_followup"
    CALL_CAPABILITY = "call_capability"
    NO_REPLY = "no_reply"


@dataclass(frozen=True)
class PlannedAction:
    action_type: ActionType
    payload: Mapping[str, Any] = field(default_factory=dict)
    action_id: str = field(default_factory=lambda: str(uuid4()))


@dataclass(frozen=True)
class ActionPlan:
    target_character_id: str
    actions: tuple[PlannedAction, ...]
    attention_notes: tuple[str, ...] = ()
    plan_id: str = field(default_factory=lambda: str(uuid4()))


@dataclass(frozen=True)
class ResponseEnvelope:
    """Channel-neutral response produced by the future runtime."""

    target_channel: str
    target_user_id: str | None
    target_character_id: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    response_id: str = field(default_factory=lambda: str(uuid4()))
    ephemeral: bool = False
