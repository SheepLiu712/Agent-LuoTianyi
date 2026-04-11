import random
from datetime import datetime
from typing import Any, Dict, List

from .amap_client import AMapClient
from .state_manager import CitywalkStateManager
from .types import CitywalkEvent, CitywalkSessionResult, POI


class CitywalkSessionRunner:
    def __init__(self, config: Dict[str, Any], client: AMapClient):
        self.config = config
        self.client = client
        sess_cfg = config.get("session", {})
        self.state_manager = CitywalkStateManager(
            initial_energy=int(sess_cfg.get("initial_energy", 100)),
            max_minutes=int(sess_cfg.get("max_minutes", 240)),
            move_energy_per_km=int(sess_cfg.get("move_energy_per_km", 5)),
            activity_energy_per_30min=int(sess_cfg.get("activity_energy_per_30min", 8)),
        )
        self.max_stops = int(sess_cfg.get("max_stops", 4))
        duration_range = sess_cfg.get("activity_duration_min", [20, 60])
        self.activity_min = int(duration_range[0])
        self.activity_max = int(duration_range[1])

    def _choose_poi(self, pois: List[POI]) -> POI:
        sorted_pois = sorted(pois, key=lambda x: x.distance_m)
        top = sorted_pois[: min(3, len(sorted_pois))]
        return random.choice(top)

    def run(self, city: str, start_location: str) -> CitywalkSessionResult:
        events: List[CitywalkEvent] = []
        current_location = start_location
        total_distance = 0

        search_cfg = self.config.get("search", {})
        keywords_pool = search_cfg.get("keywords", ["餐厅", "咖啡", "公园"])

        for _ in range(self.max_stops):
            if self.state_manager.should_end():
                break

            keyword = random.choice(keywords_pool)
            pois = self.client.search_nearby_pois(
                location=current_location,
                city=city,
                keywords=keyword,
                types=search_cfg.get("types", ""),
                radius_m=int(search_cfg.get("radius_m", 3000)),
                offset=int(search_cfg.get("offset", 10)),
            )
            if not pois:
                break

            target = self._choose_poi(pois)
            route = self.client.plan_walking_route(current_location, target.location)
            if not route.reachable:
                break

            energy_before = self.state_manager.state.energy
            self.state_manager.apply_move(route.distance_m, route.duration_s)
            activity_duration = random.randint(self.activity_min, self.activity_max)
            self.state_manager.apply_activity(activity_duration)

            thought = f"这里看起来很有意思，我想在{target.name}多待一会儿。"
            activity = f"在{target.name}体验了{keyword}相关活动，大约{activity_duration}分钟"
            events.append(
                CitywalkEvent(
                    timestamp=datetime.now(),
                    poi=target,
                    route=route,
                    activity=activity,
                    thought=thought,
                    energy_before=energy_before,
                    energy_after=self.state_manager.state.energy,
                )
            )

            total_distance += route.distance_m
            current_location = target.location

        return CitywalkSessionResult(
            city=city,
            start_location=start_location,
            end_location=current_location,
            total_distance_m=total_distance,
            total_duration_minutes=self.state_manager.state.elapsed_minutes,
            energy_left=self.state_manager.state.energy,
            events=events,
        )
