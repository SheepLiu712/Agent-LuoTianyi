import dataclasses
from typing import Optional
from enum import Enum

class ReplyIntensity(Enum):
    NORMAL = "normal"
    SERIOUS = "serious"

class SingingAction(Enum):
    NO_SINGING = "no_singing"
    PROPOSE_SINGING = "propose_singing"
    TRY_SINGING = "try_singing"

@dataclasses.dataclass
class PlanningStep:
    reply_intensity: ReplyIntensity = ReplyIntensity.NORMAL
    reply_description: Optional[str] = None
    singing_action: SingingAction = SingingAction.NO_SINGING
    singing_song: Optional[str] = None
    singing_segment: Optional[str] = None
    singing_lyrics: Optional[str] = None