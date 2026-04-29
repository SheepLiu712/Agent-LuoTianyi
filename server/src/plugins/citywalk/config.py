from typing import Any, Dict

from ...utils.helpers import load_config


DEFAULT_CITYWALK_CONFIG: Dict[str, Any] = {
    "amap": {
        "api_key": "$AMAP_KEY",
        "base_url": "https://restapi.amap.com/v3",
        "timeout_seconds": 10,
        "max_retries": 1,
    },
    "session": {
        "initial_energy": 100,
        "initial_fullness": 70,
        "initial_mood": 70,
        "max_minutes": 240,
        "max_stops": 4,
        "move_energy_per_km": 5,
        "activity_energy_per_30min": 8,
        "activity_duration_min": [20, 60],
        "start_district_code": "",
    },
    "search": {
        "radius_m": 3000,
        "offset": 10,
        "max_action_rounds": 40,
        "types": "餐饮服务|风景名胜|购物服务|休闲场所",
        "keywords": ["餐厅", "咖啡", "公园", "商场", "书店"],
    },
    "report": {
        "output_dir": "data/citywalk_reports",
        "title_prefix": "逛街小洛",
        "history_file": "data/citywalk_reports/citywalk_history.json",
    },
    "decision": {
        "enabled": True,
        "persona_path": "res/agent/persona/luotianyi_persona.json",
        "max_poi_candidates": 5,
        "constrained_rounds": 2,
        "use_llm_environment_feedback": False,
        "fail_on_error": True,
        "llm": {
            "api_type": "openai",
            "model": "qwen3.5-plus",
            "api_key": "$QWEN_API_KEY",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "temperature": 0.7,
            "max_tokens": 512,
            "max_retries": 2,
            "request_timeout_seconds": 45,
        },
        "environment": {
            "enabled": True,
            "fail_on_error": True,
            "llm": {
                "api_type": "openai",
                "model": "qwen3.5-plus",
                "api_key": "$QWEN_API_KEY",
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "temperature": 0.7,
                "max_tokens": 512,
                "max_retries": 2,
                "request_timeout_seconds": 45,
                "vlm_model": "qwen3-vl-plus",
            },
        },
    },
}


def load_citywalk_config(config_path: str = "config/config.json") -> Dict[str, Any]:
    all_config = load_config(config_path, default_config={})
    citywalk = all_config.get("citywalk", {})

    # Merge defaults manually to avoid side effects.
    merged = {
        "amap": {**DEFAULT_CITYWALK_CONFIG["amap"], **citywalk.get("amap", {})},
        "session": {**DEFAULT_CITYWALK_CONFIG["session"], **citywalk.get("session", {})},
        "search": {**DEFAULT_CITYWALK_CONFIG["search"], **citywalk.get("search", {})},
        "report": {**DEFAULT_CITYWALK_CONFIG["report"], **citywalk.get("report", {})},
        "decision": {
            **DEFAULT_CITYWALK_CONFIG["decision"],
            **citywalk.get("decision", {}),
            "llm": {
                **DEFAULT_CITYWALK_CONFIG["decision"]["llm"],
                **citywalk.get("decision", {}).get("llm", {}),
            },
            "environment": {
                **DEFAULT_CITYWALK_CONFIG["decision"]["environment"],
                **citywalk.get("decision", {}).get("environment", {}),
                "llm": {
                    **DEFAULT_CITYWALK_CONFIG["decision"]["environment"]["llm"],
                    **citywalk.get("decision", {}).get("environment", {}).get("llm", {}),
                },
            },
        },
    }
    return merged
