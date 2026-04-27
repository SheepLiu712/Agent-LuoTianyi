import json

from src.plugins.citywalk.decision_engine import CitywalkDecisionEngine
from src.plugins.citywalk.errors import LLMDecisionError
from src.plugins.citywalk.types import CitywalkState, POI


class FakeCompletions:
    def create(self, **kwargs):
        class Msg:
            content = json.dumps(
                {
                    "feeling": "这些地点都挺有趣，我先去最近的。",
                    "action": "go_to_poi",
                    "poi_index": 1,
                    "action_category": "try_food",
                    "custom_action": "",
                    "activity": "去公园散步",
                    "activity_duration_min": 35,
                    "reason": "llm_test",
                },
                ensure_ascii=False,
            )

        class Choice:
            message = Msg()

        class Resp:
            choices = [Choice()]

        return Resp()


class FakeChat:
    completions = FakeCompletions()


class FakeLLMClient:
    chat = FakeChat()


def _build_cfg():
    return {
        "session": {
            "activity_duration_min": [20, 60],
        },
        "decision": {
            "enabled": True,
            "max_poi_candidates": 5,
            "llm": {
                "api_type": "openai",
                "model": "qwen3.5-plus",
                "api_key": "test_key",
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            },
        },
    }


def test_environment_feedback_contains_candidates():
    engine = CitywalkDecisionEngine(_build_cfg(), llm_client=FakeLLMClient())
    pois = [
        POI(poi_id="1", name="咖啡店", location="1,1", address="A路", distance_m=120, type_name="餐饮"),
        POI(poi_id="2", name="公园", location="2,2", address="B路", distance_m=300, type_name="公园"),
    ]

    text = engine.build_environment_feedback(
        city="北京",
        current_location="116.3,39.9",
        keyword="公园",
        pois=pois,
        state=CitywalkState(energy=88, elapsed_minutes=40),
    )

    assert "附近候选地点" in text
    assert "咖啡店" in text
    assert "公园" in text


def test_decide_uses_llm_json_and_clamps_duration():
    engine = CitywalkDecisionEngine(_build_cfg(), llm_client=FakeLLMClient())
    pois = [
        POI(poi_id="1", name="书店", location="1,1", distance_m=500),
        POI(poi_id="2", name="公园", location="2,2", distance_m=300),
    ]

    decision = engine.decide(
        city="北京",
        current_location="116.3,39.9",
        keyword="公园",
        pois=pois,
        state=CitywalkState(energy=88, elapsed_minutes=40),
        history_events=[],
    )

    assert decision.action == "go_to_poi"
    assert decision.poi_index == 1
    assert decision.action_category == "try_food"
    assert decision.activity_duration_min == 35
    assert "最近" in decision.feeling


def test_decide_raises_when_llm_output_invalid():
    class BadCompletions:
        def create(self, **kwargs):
            class Msg:
                content = "{}"

            class Choice:
                message = Msg()

            class Resp:
                choices = [Choice()]

            return Resp()

    class BadChat:
        completions = BadCompletions()

    class BadClient:
        chat = BadChat()

    engine = CitywalkDecisionEngine(_build_cfg(), llm_client=BadClient())
    pois = [POI(poi_id="1", name="书店", location="1,1", distance_m=500)]

    try:
        engine.decide(
            city="北京",
            current_location="116.3,39.9",
            keyword="书店",
            pois=pois,
            state=CitywalkState(energy=88, elapsed_minutes=40),
            history_events=[],
        )
    except LLMDecisionError as exc:
        assert "决策LLM多次失败" in str(exc)
    else:
        raise AssertionError("Expected LLMDecisionError")
