import json
from pathlib import Path
from typing import Any, Dict, List


def load_citywalk_history(history_file: str) -> List[Dict[str, Any]]:
    path = Path(history_file)
    if not path.exists():
        return []
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(content, list):
        return []
    rows: List[Dict[str, Any]] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        city = str(item.get("city", "")).strip()
        places = item.get("places", [])
        if isinstance(places, str):
            places = [places]
        if not isinstance(places, list):
            places = []
        cleaned_places = [str(p).strip() for p in places if str(p).strip()]
        rows.append({"city": city, "places": cleaned_places})
    return rows


def get_recent_citywalk_history(history_file: str, limit: int = 10) -> List[Dict[str, Any]]:
    rows = load_citywalk_history(history_file)
    if limit <= 0:
        return []
    return rows[-limit:]


def append_citywalk_history(history_file: str, city: str, places: List[str]) -> None:
    path = Path(history_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = load_citywalk_history(history_file)
    rows.append(
        {
            "city": str(city or "").strip(),
            "places": [str(p).strip() for p in places if str(p).strip()],
        }
    )
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
