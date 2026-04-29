from src.plugins.citywalk.environment_engine import CitywalkEnvironmentEngine
from src.plugins.citywalk.errors import LLMEnvironmentError
from src.plugins.citywalk.types import POI, POIDetail


def _build_cfg():
    return {
        "decision": {
            "fail_on_error": False,
            "environment": {
                "enabled": False,
                "fail_on_error": False,
                "llm": {
                    "api_key": "",
                },
            }
        }
    }


def test_environment_engine_rule_generate_food_activity():
    engine = CitywalkEnvironmentEngine(_build_cfg())
    poi = POI(poi_id="1", name="测试餐馆", location="1,1", type_name="餐饮")
    detail = POIDetail(poi=poi, rating=4.5, intro="招牌蒸点")

    result = engine.generate(
        city="北京",
        poi=poi,
        action_category="try_food",
        custom_action="",
        keyword="餐厅",
        state_energy=80,
        state_minutes=60,
        poi_detail=detail,
    )

    assert result.activity
    assert result.event
    assert -10 <= result.delta_energy <= 3
    assert 5 <= result.delta_minutes <= 30
    assert len(result.next_actions) >= 2


def test_environment_engine_raises_when_enabled_and_output_invalid():
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

    cfg = {
        "decision": {
            "environment": {
                "enabled": True,
                "fail_on_error": True,
                "llm": {
                    "api_key": "test_key",
                    "max_retries": 1,
                },
            }
        }
    }
    engine = CitywalkEnvironmentEngine(cfg, llm_client=BadClient())
    poi = POI(poi_id="1", name="测试餐馆", location="1,1", type_name="餐饮")

    try:
        engine.generate(
            city="北京",
            poi=poi,
            action_category="try_food",
            custom_action="",
            keyword="餐厅",
            state_energy=80,
            state_minutes=60,
            poi_detail=None,
        )
    except LLMEnvironmentError as exc:
        assert "环境LLM多次失败" in str(exc)
    else:
        raise AssertionError("Expected LLMEnvironmentError")
