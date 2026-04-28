import json
from pathlib import Path
from typing import Any, Dict, List

from ...utils.helpers import ensure_directory
from .history_store import append_citywalk_history
from .types import CitywalkSessionResult


class CitywalkReportGenerator:
    def __init__(self, title_prefix: str = "逛街小洛", history_file: str = "data/citywalk_reports/citywalk_history.json"):
        self.title_prefix = title_prefix
        self.history_file = history_file

    def build_payload(self, result: CitywalkSessionResult) -> Dict[str, Any]:
        places: List[str] = [e.poi.name for e in result.events if e.poi and e.poi.name]
        event_cards: List[Dict[str, Any]] = []
        for idx, event in enumerate(result.events, start=1):
            event_cards.append(
                {
                    "index": idx,
                    "time": event.timestamp.strftime("%H:%M"),
                    "poi": {
                        "name": event.poi.name,
                        "address": event.poi.address,
                        "type_name": event.poi.type_name,
                    },
                    "route": {
                        "distance_m": event.route.distance_m,
                        "duration_s": event.route.duration_s,
                    },
                    "reason": event.llm_reason,
                    "moving_activity": event.moving_activity,
                    "poi_activity": event.poi_activity,
                    "state": {
                        "energy": [event.energy_before, event.energy_after],
                        "fullness": [event.fullness_before, event.fullness_after],
                        "mood": [event.mood_before, event.mood_after],
                    },
                }
            )

        return {
            "title": self.title_prefix,
            "created_at": result.created_at.isoformat(),
            "overview": {
                "city": result.city,
                "selected_destination": result.selected_destination,
                "destination_reason": result.destination_reason,
                "start_location": result.start_location,
                "end_location": result.end_location,
                "total_duration_minutes": result.total_duration_minutes,
                "total_distance_m": result.total_distance_m,
                "energy_left": result.energy_left,
            },
            "places": places,
            "event_cards": event_cards,
            "poi_details": result.poi_details,
            "diary_text": result.diary_text,
        }

    def render(self, result: CitywalkSessionResult) -> str:
        return json.dumps(self.build_payload(result), ensure_ascii=False, indent=2)

    def save(self, result: CitywalkSessionResult, output_dir: str) -> str:
        ensure_directory(output_dir)
        session_tag = result.created_at.strftime("%Y%m%d_%H%M%S")
        filename = f"citywalk_{session_tag}.json"
        output_path = Path(output_dir) / filename
        output_path.write_text(self.render(result), encoding="utf-8")

        places = [e.poi.name for e in result.events if e.poi and e.poi.name]
        append_citywalk_history(self.history_file, city=result.city, places=places)
        return str(output_path)
