from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class POI:
    poi_id: str
    name: str
    location: str
    address: str = ""
    distance_m: int = 0
    type_name: str = ""


@dataclass
class POIDetail:
    poi: POI
    tel: str = ""
    rating: Optional[float] = None
    business_hours: str = ""
    intro: str = ""


@dataclass
class RouteResult:
    reachable: bool
    distance_m: int
    duration_s: int
    steps: List[str] = field(default_factory=list)


@dataclass
class CitywalkState:
    energy: int = 100
    elapsed_minutes: int = 0


@dataclass
class CitywalkEvent:
    timestamp: datetime
    poi: POI
    route: RouteResult
    activity: str
    thought: str
    energy_before: int
    energy_after: int


@dataclass
class CitywalkSessionResult:
    city: str
    start_location: str
    end_location: str
    total_distance_m: int
    total_duration_minutes: int
    energy_left: int
    events: List[CitywalkEvent]
    created_at: datetime = field(default_factory=datetime.now)
