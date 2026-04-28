import json
from datetime import datetime
from pathlib import Path

from src.plugins.citywalk.report_generator import CitywalkReportGenerator
from src.plugins.citywalk.types import CitywalkEvent, CitywalkSessionResult, POI, RouteResult


def _build_result() -> CitywalkSessionResult:
    poi = POI(
        poi_id="1",
        name="测试咖啡店",
        location="116.3,39.9",
        address="测试路1号",
        distance_m=500,
        type_name="餐饮",
    )
    route = RouteResult(reachable=True, distance_m=500, duration_s=420, steps=["向北步行"])
    event = CitywalkEvent(
        timestamp=datetime(2026, 4, 11, 10, 30),
        poi=poi,
        route=route,
        poi_content={"rating": 4.6, "signature_or_tags": ["咖啡"]},
        moving_activity="步行约7分钟到达测试咖啡店",
        poi_activity="停留30分钟，喝了拿铁",
        energy_before=90,
        energy_after=82,
        mood_before=70,
        mood_after=78,
        fullness_before=60,
        fullness_after=66,
        travel_min=7,
        activity_min=30,
        activity="喝了拿铁",
        environment_feedback="环境事件: 看到街头艺人",
        llm_action="relax_walk@poi:auto",
        llm_reason="mock_llm",
    )
    return CitywalkSessionResult(
        city="北京",
        start_location="116.39,39.90",
        end_location="116.3,39.9",
        total_distance_m=500,
        total_duration_minutes=37,
        energy_left=82,
        events=[event],
        created_at=datetime(2026, 4, 11, 12, 0),
        selected_destination="南锣鼓巷",
        destination_reason="想去胡同感受烟火气",
        diary_text="10:30 测试咖啡店 喝了拿铁",
    )


def test_report_render_json_payload():
    result = _build_result()
    payload = json.loads(CitywalkReportGenerator().render(result))

    assert payload["overview"]["city"] == "北京"
    assert payload["places"] == ["测试咖啡店"]
    assert payload["event_cards"][0]["poi"]["name"] == "测试咖啡店"
    assert payload["event_cards"][0]["state"]["energy"] == [90, 82]


def test_report_save_json_and_history(tmp_path):
    output_dir = tmp_path / "reports"
    history_file = tmp_path / "citywalk_history.json"

    result = _build_result()
    generator = CitywalkReportGenerator(history_file=str(history_file))
    output_path = generator.save(result, str(output_dir))

    assert output_path.endswith(".json")
    content = json.loads(Path(output_path).read_text(encoding="utf-8"))
    assert content["overview"]["city"] == "北京"

    history = json.loads(history_file.read_text(encoding="utf-8"))
    assert isinstance(history, list)
    assert history[-1] == {"city": "北京", "places": ["测试咖啡店"]}
