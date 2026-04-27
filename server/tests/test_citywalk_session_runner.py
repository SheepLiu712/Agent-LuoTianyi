from src.plugins.citywalk.session_runner import CitywalkSessionRunner
from src.plugins.citywalk.types import POI, POIDetail, RouteResult


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

    def get_poi_detail(self, poi_id):
        poi = POI(poi_id=poi_id, name="测试公园", location="116.40,39.91", type_name="公园")
        return POIDetail(poi=poi, rating=4.6, intro="绿化好")


class FakeDecision:
    def build_environment_feedback(self, city, current_location, keyword, pois, state):
        return f"在{city}探索{keyword}，候选点{len(pois)}个"

    def decide(self, city, current_location, keyword, pois, state, history_events):
        class R:
            action = "go_to_poi"
            poi_index = 0
            activity_duration_min = 20
            feeling = "这地方让我很有灵感，想去看看。"
            activity = f"在{pois[0].name}体验{keyword}"
            action_category = "relax_walk"
            custom_action = ""
            reason = "mock_llm"

        return R()


class FakeEnvironment:
    def generate(self, **kwargs):
        class E:
            activity = "在测试公园慢跑后拍了两张街景。"
            event = "遇到街头艺人演奏。"
            feeling_update = "心情轻快了不少。"
            delta_energy = -3
            delta_minutes = 10
            next_actions = ["go_to_poi", "custom_action", "return"]

        return E()


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
    runner = CitywalkSessionRunner(
        cfg,
        FakeClient(),
        decision_engine=FakeDecision(),
        environment_engine=FakeEnvironment(),
    )
    result = runner.run(city="北京", start_location="116.39,39.90")

    assert len(result.events) >= 1
    assert result.total_distance_m >= 300
    assert result.energy_left < 100
    assert result.events[0].llm_action.startswith("relax_walk@poi")
    assert "环境事件" in result.events[0].environment_feedback
    assert "慢跑" in result.events[0].activity
