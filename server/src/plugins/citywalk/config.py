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
        "max_minutes": 240,
        "max_stops": 4,
        "move_energy_per_km": 5,
        "activity_energy_per_30min": 8,
        "activity_duration_min": [20, 60],
    },
    "search": {
        "radius_m": 3000,
        "offset": 10,
        "types": "050000|060000|110000|120000",
        "keywords": ["餐厅", "咖啡", "公园", "商场", "书店"],
    },
    "report": {
        "output_dir": "data/citywalk_reports",
        "title_prefix": "逛街小洛",
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
    }
    return merged
