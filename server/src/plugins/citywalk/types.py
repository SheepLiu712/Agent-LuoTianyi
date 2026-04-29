from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
import random


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
    tags: List[str] = field(default_factory=list)
    photos: List[str] = field(default_factory=list)


@dataclass
class RouteResult:
    reachable: bool
    distance_m: int
    duration_s: int
    steps: List[str] = field(default_factory=list)


@dataclass
class CitywalkState:
    energy: int = 100
    fullness: int = 70
    mood: int = 70
    elapsed_minutes: int = 0


@dataclass
class LocationDialogueTurn:
    role: str
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    action_name: str = ""


@dataclass
class CitywalkEvent:
    timestamp: datetime
    poi: POI
    route: RouteResult
    poi_content: Dict[str, Any]
    moving_activity: str
    poi_activity: str
    energy_before: int
    energy_after: int
    mood_before: int
    mood_after: int
    fullness_before: int
    fullness_after: int
    travel_min: int
    activity_min: int
    activity: str = ""
    environment_feedback: str = ""
    llm_action: str = ""
    llm_reason: str = ""
    keyword: str = ""
    search_result: str = ""

    def __str__(self):
        return f"选这里的理由：{self.llm_reason}。{self.moving_activity}, {self.poi_activity} 能量：{self.energy_before}→{self.energy_after}，心情：{self.mood_before}→{self.mood_after}，饱腹度：{self.fullness_before}→{self.fullness_after}"
    


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
    selected_destination: str = ""
    destination_reason: str = ""
    poi_details: List[Dict[str, Any]] = field(default_factory=list)
    diary_text: str = ""


@dataclass
class CitywalkSessionData:
    current_location: str = ""
    current_location_name: str = ""
    city: str = ""
    events: List[CitywalkEvent] = field(default_factory=list)
    visited_ids: Set[str] = field(default_factory=set)
    visited_names: List[str] = field(default_factory=list)
    session_start_location: Optional[str] = None
    poi_details: List[Dict[str, Any]] = field(default_factory=list)
    total_distance: int = 0
    food_count: int = 0
    play_count: int = 0
    current_time: datetime = field(
        default_factory=lambda: datetime.now().replace(hour=9, minute=random.randint(20, 50), second=0, microsecond=0)
    )
    lucky_number: float = field(default_factory=lambda: random.gauss(60, 10))

@dataclass
class POIFeedBack:
    environment_feedback: str = ""
    mood_change: int = 0
    energy_change: int = 0
    fullness_change: int = 0
    stay_minutes: int = 0