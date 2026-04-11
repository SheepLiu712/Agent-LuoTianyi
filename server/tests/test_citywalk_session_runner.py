from src.plugins.citywalk.session_runner import CitywalkSessionRunner
from src.plugins.citywalk.types import POI, RouteResult


class FakeClient:
    def search_nearby_pois(self, **kwargs):
        return [
            POI(
                poi_id="1",
                name="测试公园",
                location="116.40,39.91",
                address="测试地址",
                distance_m=300,
                type_name="公园",
            )
        ]

    def plan_walking_route(self, origin, destination):
        return RouteResult(reachable=True, distance_m=300, duration_s=300, steps=["步行"])


def test_session_runner_generates_events():
    cfg = {
        "session": {
            "initial_energy": 100,
            "max_minutes": 120,
            "max_stops": 2,
            "move_energy_per_km": 5,
            "activity_energy_per_30min": 8,
            "activity_duration_min": [20, 20],
        },
        "search": {
            "types": "110000",
            "radius_m": 2000,
            "offset": 5,
            "keywords": ["公园"],
        },
    }
    runner = CitywalkSessionRunner(cfg, FakeClient())
    result = runner.run(city="北京", start_location="116.39,39.90")

    assert len(result.events) >= 1
    assert result.total_distance_m >= 300
    assert result.energy_left < 100
