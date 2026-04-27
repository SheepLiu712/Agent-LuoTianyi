import os
import sys

# Setup paths
current_dir = os.getcwd()
if current_dir not in sys.path:
    sys.path.append(current_dir)

from datetime import datetime

from src.plugins.citywalk.report_generator import CitywalkReportGenerator
from src.plugins.citywalk.types import CitywalkEvent, CitywalkSessionResult, POI, RouteResult


def test_report_render_contains_cards():
    poi = POI(poi_id="1", name="测试咖啡店", location="116.3,39.9", address="测试路1号", distance_m=500, type_name="餐饮")
    route = RouteResult(reachable=True, distance_m=500, duration_s=420, steps=["向北步行"])
    event = CitywalkEvent(
        timestamp=datetime(2026, 4, 11, 10, 30),
        poi=poi,
        route=route,
        activity="喝咖啡",
        thought="今天状态不错",
        energy_before=90,
        energy_after=82,
        keyword="咖啡",
        activity_duration_min=30,
        search_result="测试咖啡店(500m,餐饮)",
        environment_feedback="附近有一家评价不错的咖啡店，步行可达。",
        available_actions=["go_to_poi:0", "return"],
        llm_action="go_to_poi:0",
        llm_reason="mock_llm",
    )
    result = CitywalkSessionResult(
        city="北京",
        start_location="116.39,39.90",
        end_location="116.3,39.9",
        total_distance_m=500,
        total_duration_minutes=37,
        energy_left=82,
        events=[event],
    )

    text = CitywalkReportGenerator().render(result)
    assert "地点卡片" in text
    assert "第1站" in text
    assert "测试咖啡店" in text
    assert "体力变化: 90 -> 82" in text
    assert "LLM选择: go_to_poi:0" in text
    assert "高德候选" in text
