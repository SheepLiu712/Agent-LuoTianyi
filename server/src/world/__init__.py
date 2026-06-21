"""World and sandbox-facing adapters.

The first refactor phase keeps existing plugin implementations in place and
exposes them through world-facing facades. Later phases can move the concrete
providers behind these boundaries.
"""

from src.world.events import WorldEvent, WorldEventProvider
from src.world.public_diary import CitywalkDiaryProvider, PublicDiaryEntry
from src.world.schedule_provider import ScheduleWorldProvider

__all__ = [
    "CitywalkDiaryProvider",
    "PublicDiaryEntry",
    "ScheduleWorldProvider",
    "WorldEvent",
    "WorldEventProvider",
]
