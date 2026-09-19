"""聊天交互持有的输入状态和回复尝试。"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

import src.domain.agent as d


class _InputStatus(Enum):
    PREPROCESSING = "preprocessing"
    READY = "ready"
    REPLYING = "replying"


@dataclass
class _PendingInput:
    stimulus: d.Stimulus
    sequence: int
    status: _InputStatus = _InputStatus.PREPROCESSING
    prepared: d.PreprocessedInput | None = None
    ready_at: datetime | None = None


@dataclass
class _ReplyAttempt:
    request: d.HandleStimulusRequest
    input_ids: tuple[str, ...]
    remaining_plans: set[str] = field(default_factory=set)
    report: d.HandlingReport | None = None
    interrupted: bool = False
